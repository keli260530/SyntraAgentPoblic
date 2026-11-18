"""
Syntra Pathways-Style Single-Controller DAG Orchestrator
借鏡 Google Pathways Single-Controller 架構：
1. Single-Controller 中央排程器 + 事件驅動 Ready Queue（上游一完成即刻派發已就緒之下游，不被慢分支鎖死）
2. 節點級彈性重映射 (Elastic Remapping)：單一節點失敗時自動重映射至健康備援執行器，保留上游快取不整批重來
3. 局部故障隔離：單一分支失敗僅阻斷相依下游，獨立分支照常完成
"""

from __future__ import annotations

import asyncio
import inspect
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Tuple


NodeCallable = Callable[..., Any]


@dataclass
class TaskNode:
    id: str
    fn: NodeCallable
    deps: Tuple[str, ...] = ()
    fallback_fns: Tuple[NodeCallable, ...] = ()
    timeout_sec: Optional[float] = None
    name: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.deps = tuple(self.deps or ())
        self.fallback_fns = tuple(self.fallback_fns or ())
        if not self.name:
            self.name = self.id


@dataclass
class NodeResult:
    id: str
    status: str  # "done" | "remapped" | "failed" | "skipped"
    value: Any = None
    error: str = ""
    attempt_count: int = 0
    remapped_index: int = 0  # 0 = primary, >0 = fallback index
    elapsed_ms: float = 0.0


class PathwaysCycleError(ValueError):
    """DAG 存在循環依賴時拋出。"""


class PathwaysOrchestrator:
    """事件驅動之單一總控非同步 DAG 執行引擎。"""

    def __init__(
        self,
        max_concurrency: int = 6,
        on_event: Optional[Callable[[Dict[str, Any]], Any]] = None,
    ) -> None:
        self.max_concurrency = max(1, int(max_concurrency))
        self.on_event = on_event

    async def _emit(self, event: Dict[str, Any]) -> None:
        if not self.on_event:
            return
        try:
            res = self.on_event(event)
            if inspect.isawaitable(res):
                await res
        except Exception:
            pass

    @staticmethod
    def _validate_dag(nodes: Dict[str, TaskNode]) -> None:
        for nid, node in nodes.items():
            for dep in node.deps:
                if dep not in nodes:
                    raise ValueError(f"TaskNode '{nid}' references unknown dependency '{dep}'")

        state: Dict[str, int] = {}  # 0=unvisited, 1=visiting, 2=visited

        def dfs(curr: str) -> None:
            st = state.get(curr, 0)
            if st == 1:
                raise PathwaysCycleError(f"Cycle detected involving node '{curr}'")
            if st == 2:
                return
            state[curr] = 1
            for dep in nodes[curr].deps:
                dfs(dep)
            state[curr] = 2

        for nid in nodes:
            if state.get(nid, 0) == 0:
                dfs(nid)

    @staticmethod
    async def _invoke(fn: NodeCallable, dep_outputs: Dict[str, Any], node: TaskNode) -> Any:
        sig = inspect.signature(fn)
        params = sig.parameters
        accepts_ctx = "ctx" in params or any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()
        )
        if accepts_ctx:
            res = fn(ctx=dep_outputs)
        elif len(params) == 1:
            res = fn(dep_outputs)
        else:
            res = fn()
        if inspect.isawaitable(res):
            if node.timeout_sec is not None and node.timeout_sec > 0:
                return await asyncio.wait_for(res, timeout=node.timeout_sec)
            return await res
        return res

    async def run(self, nodes_list: Iterable[TaskNode]) -> Dict[str, NodeResult]:
        nodes: Dict[str, TaskNode] = {}
        for n in nodes_list:
            if n.id in nodes:
                raise ValueError(f"Duplicate TaskNode id '{n.id}'")
            nodes[n.id] = n

        if not nodes:
            return {}

        self._validate_dag(nodes)

        dependents: Dict[str, List[str]] = {nid: [] for nid in nodes}
        pending_deps: Dict[str, int] = {}
        for nid, node in nodes.items():
            pending_deps[nid] = len(node.deps)
            for dep in node.deps:
                dependents[dep].append(nid)

        sem = asyncio.Semaphore(self.max_concurrency)
        results: Dict[str, NodeResult] = {}
        active_tasks: Dict[str, asyncio.Task] = {}

        async def _run_node(node: TaskNode) -> NodeResult:
            t0 = time.perf_counter()
            dep_outputs = {d: results[d].value for d in node.deps}
            candidates = (node.fn,) + node.fallback_fns
            last_err = ""

            async with sem:
                await self._emit({"type": "NODE_RUNNING", "node_id": node.id, "name": node.name})
                for idx, fn in enumerate(candidates):
                    try:
                        val = await self._invoke(fn, dep_outputs, node)
                        elapsed = (time.perf_counter() - t0) * 1000.0
                        status = "remapped" if idx > 0 else "done"
                        if idx > 0:
                            await self._emit({
                                "type": "NODE_REMAPPED",
                                "node_id": node.id,
                                "fallback_index": idx,
                            })
                        return NodeResult(
                            id=node.id,
                            status=status,
                            value=val,
                            attempt_count=idx + 1,
                            remapped_index=idx,
                            elapsed_ms=elapsed,
                        )
                    except Exception as exc:
                        last_err = f"{type(exc).__name__}: {exc}"
                        if idx + 1 < len(candidates):
                            await self._emit({
                                "type": "NODE_RETRY_REMAP",
                                "node_id": node.id,
                                "failed_attempt": idx + 1,
                                "error": last_err,
                            })

            elapsed = (time.perf_counter() - t0) * 1000.0
            return NodeResult(
                id=node.id,
                status="failed",
                error=last_err,
                attempt_count=len(candidates),
                remapped_index=0,
                elapsed_ms=elapsed,
            )

        def _schedule(nid: str) -> None:
            active_tasks[nid] = asyncio.create_task(_run_node(nodes[nid]))

        def _mark_skipped_downstream(failed_id: str) -> None:
            queue = list(dependents[failed_id])
            while queue:
                child_id = queue.pop(0)
                if child_id in results or child_id in active_tasks:
                    continue
                results[child_id] = NodeResult(
                    id=child_id,
                    status="skipped",
                    error=f"Upstream dependency '{failed_id}' failed/skipped",
                )
                queue.extend(dependents[child_id])

        for nid, cnt in pending_deps.items():
            if cnt == 0:
                _schedule(nid)

        while active_tasks:
            done_set, _ = await asyncio.wait(
                active_tasks.values(),
                return_when=asyncio.FIRST_COMPLETED,
            )
            finished_ids = [nid for nid, t in active_tasks.items() if t in done_set]
            for nid in finished_ids:
                task = active_tasks.pop(nid)
                res = task.result()
                results[nid] = res
                await self._emit({
                    "type": "NODE_FINISHED",
                    "node_id": nid,
                    "status": res.status,
                    "elapsed_ms": round(res.elapsed_ms, 2),
                })
                if res.status == "failed":
                    _mark_skipped_downstream(nid)
                    continue
                for child_id in dependents[nid]:
                    if child_id in results:
                        continue
                    pending_deps[child_id] -= 1
                    if pending_deps[child_id] == 0:
                        _schedule(child_id)

        return results

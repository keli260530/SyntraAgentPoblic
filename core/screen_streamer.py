import datetime
from pathlib import Path
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
from PIL import Image

from PyQt5.QtCore import QObject, QTimer, pyqtSignal
from PyQt5.QtGui import QImage, QPixmap


class ScreenRecorder:
    """
    職責：錄製指定視窗或全螢幕畫面為高畫質 MP4 影片檔。
    """
    def __init__(self, output_dir: Optional[Path] = None):
        base_dir = Path(__file__).resolve().parent.parent
        self.output_dir = output_dir or (base_dir / "data" / "recordings")
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.is_recording = False
        self.writer: Optional[Any] = None  # cv2.VideoWriter（錄影時才載入 OpenCV）
        self.current_filepath: Optional[Path] = None
        self.start_time: float = 0.0
        self.frame_count: int = 0
        self.fps: float = 12.0
        self.frame_size: Tuple[int, int] = (1280, 720)

    def start(self, width: int = 1280, height: int = 720, fps: float = 12.0) -> Path:
        if self.is_recording:
            self.stop()

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.current_filepath = self.output_dir / f"recording_{timestamp}.mp4"
        self.fps = fps
        self.frame_size = (width, height)

        import cv2  # 延遲載入：只有錄影才需要 OpenCV（約 20MB）

        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        self.writer = cv2.VideoWriter(
            str(self.current_filepath),
            fourcc,
            self.fps,
            self.frame_size,
        )
        self.is_recording = True
        self.start_time = time.time()
        self.frame_count = 0
        return self.current_filepath

    def write_frame(self, pil_img: Image.Image):
        if not self.is_recording or not self.writer:
            return

        try:
            import cv2
            import numpy as np

            resized = pil_img.resize(self.frame_size, Image.Resampling.BILINEAR)
            # RGB 轉 BGR (OpenCV 格式)
            frame_bgr = cv2.cvtColor(np.array(resized), cv2.COLOR_RGB2BGR)
            self.writer.write(frame_bgr)
            self.frame_count += 1
        except Exception:
            pass

    def stop(self) -> Optional[Dict[str, Any]]:
        if not self.is_recording:
            return None

        self.is_recording = False
        duration = round(time.time() - self.start_time, 1)
        if self.writer:
            self.writer.release()
            self.writer = None

        res = {
            "path": str(self.current_filepath) if self.current_filepath else "",
            "filename": self.current_filepath.name if self.current_filepath else "",
            "duration_seconds": duration,
            "frame_count": self.frame_count,
        }
        return res

    def get_status(self) -> Dict[str, Any]:
        return {
            "is_recording": self.is_recording,
            "elapsed_seconds": round(time.time() - self.start_time, 1) if self.is_recording else 0.0,
            "frame_count": self.frame_count,
            "filepath": str(self.current_filepath) if self.current_filepath else None,
        }


class ScreenStreamer(QObject):
    """
    職責：以指定幀率即時同步串流目前螢幕或指定視窗畫面（類似 Discord 螢幕分享的即時流），
    同時支援即時將影格推送給 ScreenRecorder 進行同步錄影。
    """
    sig_frame_ready = pyqtSignal(QPixmap, Image.Image)
    sig_recording_tick = pyqtSignal(float, int)  # (elapsed_seconds, frame_count)

    def __init__(self, desktop_controller, fps: int = 10, parent=None):
        super().__init__(parent)
        self.desktop_controller = desktop_controller
        self.fps = fps
        self.target_hwnd: int = 0
        self.recorder = ScreenRecorder()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._capture_tick)
        self.is_streaming = False
        # 回傳 False 時（視窗縮在托盤 / 最小化）跳過截圖：沒人看的預覽不必每秒抓 12 張全螢幕。
        # 錄影中則一律照抓。
        self.should_capture: Callable[[], bool] = lambda: True

    def set_target_window(self, hwnd: int):
        self.target_hwnd = int(hwnd)

    def start_stream(self):
        if not self.is_streaming:
            interval_ms = int(1000 / self.fps)
            self._timer.start(interval_ms)
            self.is_streaming = True

    def stop_stream(self):
        if self.is_streaming:
            self._timer.stop()
            self.is_streaming = False

    def start_recording(self) -> Path:
        # 確保串流有在跑
        if not self.is_streaming:
            self.start_stream()
        return self.recorder.start(fps=float(self.fps))

    def stop_recording(self) -> Optional[Dict[str, Any]]:
        return self.recorder.stop()

    def _capture_tick(self):
        if not self.recorder.is_recording:
            try:
                if not self.should_capture():
                    return
            except Exception:
                pass
        try:
            img, _ = self.desktop_controller.capture_window_background(
                self.target_hwnd, draw_grid=False
            )
            if not img:
                return

            # 若正在錄影，寫入 VideoWriter
            if self.recorder.is_recording:
                self.recorder.write_frame(img)
                stat = self.recorder.get_status()
                self.sig_recording_tick.emit(stat["elapsed_seconds"], stat["frame_count"])

            # 轉換為 QPixmap 供 Qt UI 即時流暢渲染 (使用 .copy() 確保緩衝區安全)
            img_rgb = img.convert("RGB")
            data = img_rgb.tobytes("raw", "RGB")
            qimg = QImage(data, img.width, img.height, img.width * 3, QImage.Format_RGB888).copy()
            pix = QPixmap.fromImage(qimg)

            self.sig_frame_ready.emit(pix, img)
        except Exception:
            pass

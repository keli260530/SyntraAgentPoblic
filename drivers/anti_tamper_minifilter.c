/*
 * Windows Kernel-Mode Anti-Tamper Minifilter Driver & Process Self-Defense
 * Architecture: Ring 0 (Kernel Mode)
 *
 * 核心能力：
 * 1. IRP_MJ_CREATE / IRP_MJ_WRITE / IRP_MJ_SET_INFORMATION 核心級硬性阻斷 (Minifilter Pre-Operation Callback)
 * 2. ObRegisterCallbacks 進程與控制代碼保護：剝離 PROCESS_TERMINATE / PROCESS_VM_WRITE / PROCESS_DUP_HANDLE
 *    徹底防禦 DuplicateHandle 遠端摘除 Handle 與惡意殺行程 (Anti-Handle-Stealing & Anti-Kill)
 * 3. DASD 磁區直寫攔截：阻斷針對 \\.\PhysicalDrive* 與 \\.\C: 的原始磁區無檔案破壞 (Anti-Raw-Disk-Wiper)
 */

#include <fltKernel.h>
#include <dontuse.h>
#include <suppress.h>

#define DRIVER_TAG 'kAtG'
#define MAX_PROTECTED_PATHS 128

// 儲存受保護路徑名單 (Kernel Memory)
typedef struct _PROTECTED_ITEM {
    WCHAR Path[512];
    ULONG PathLength;
} PROTECTED_ITEM, *PPROTECTED_ITEM;

static PROTECTED_ITEM g_ProtectedPaths[MAX_PROTECTED_PATHS];
static ULONG g_ProtectedCount = 0;
static ULONG g_GuardianPid = 0;  // 守護進程 (Python Agent) 的 PID
static PFLT_FILTER g_FilterHandle = NULL;
static PVOID g_ObRegistrationHandle = NULL;

// ================= 1. ObRegisterCallbacks: 進程與控制代碼核心自衛 =================
OB_PREOP_CALLBACK_STATUS AntiTamperProcessPreCallback(
    PVOID RegistrationContext,
    POB_PRE_OPERATION_INFORMATION OperationInformation
) {
    UNREFERENCED_PARAMETER(RegistrationContext);

    // 檢查目標對象是否為進程
    if (OperationInformation->ObjectType != *PsProcessType) {
        return OB_PREOP_SUCCESS;
    }

    PEPROCESS TargetProcess = (PEPROCESS)OperationInformation->Object;
    HANDLE TargetPid = PsGetProcessId(TargetProcess);

    // 若目標進程為守護進程 (Agent)，直接在核心剝離危害權限
    if (g_GuardianPid != 0 && (ULONG_PTR)TargetPid == g_GuardianPid) {
        PEPROCESS CurrentProcess = PsGetCurrentProcess();
        HANDLE CurrentPid = PsGetProcessId(CurrentProcess);

        // 自己存取放行；外部任何行程一律剝離終止與句柄複製權限
        if (CurrentPid != TargetPid) {
            ACCESS_MASK MaskToStrip = (PROCESS_TERMINATE | 
                                      PROCESS_VM_OPERATION | 
                                      PROCESS_VM_WRITE | 
                                      PROCESS_DUP_HANDLE | 
                                      PROCESS_SUSPEND_RESUME);

            // 拔除遠端句柄複製與關閉權限，徹底杜絕 DuplicateHandle(DUPLICATE_CLOSE_SOURCE)
            OperationInformation->Parameters->CreateHandleInformation.DesiredAccess &= ~MaskToStrip;
            OperationInformation->Parameters->DuplicateHandleInformation.DesiredAccess &= ~MaskToStrip;
        }
    }

    return OB_PREOP_SUCCESS;
}

// ================= 2. Minifilter Pre-Operation: 核心檔案與磁區直寫阻斷 =================
FLT_PREOP_CALLBACK_STATUS AntiTamperPreCreate(
    PFLT_CALLBACK_DATA Data,
    PCFLT_RELATED_OBJECTS FltObjects,
    PVOID* CompletionContext
) {
    UNREFERENCED_PARAMETER(FltObjects);
    UNREFERENCED_PARAMETER(CompletionContext);

    PFLT_FILE_NAME_INFORMATION nameInfo = NULL;
    NTSTATUS status;

    // 取得當前請求進程 PID
    PEPROCESS RequestorProcess = FltGetRequestorProcess(Data);
    HANDLE RequestorPid = RequestorProcess ? PsGetProcessId(RequestorProcess) : 0;

    // 信任本機守護進程放行
    if (g_GuardianPid != 0 && (ULONG_PTR)RequestorPid == g_GuardianPid) {
        return FLT_PREOP_SUCCESS_NO_CALLBACK;
    }

    // 取得檔案路徑
    status = FltGetFileNameInformation(Data, FLT_FILE_NAME_NORMALIZED | FLT_FILE_NAME_QUERY_DEFAULT, &nameInfo);
    if (!NT_SUCCESS(status)) {
        return FLT_PREOP_SUCCESS_NO_CALLBACK;
    }
    FltParseFileNameInformation(nameInfo);

    // A. 攔截原始磁區直寫 (Raw Disk DASD Access: \\.\PhysicalDrive 或 \\.\Volume)
    if (wcsstr(nameInfo->Name.Buffer, L"\\Device\\Harddisk") != NULL) {
        ACCESS_MASK desiredAccess = Data->Iopb->Parameters.Create.SecurityContext->DesiredAccess;
        if (desiredAccess & (FILE_WRITE_DATA | FILE_APPEND_DATA | GENERIC_WRITE)) {
            // 阻斷原始扇區覆寫破壞！
            FltReleaseFileNameInformation(nameInfo);
            Data->IoStatus.Status = STATUS_ACCESS_DENIED;
            Data->IoStatus.Information = 0;
            return FLT_PREOP_COMPLETE;
        }
    }

    // B. 比對受保護目錄/檔案清單
    for (ULONG i = 0; i < g_ProtectedCount; i++) {
        if (wcsstr(nameInfo->Name.Buffer, g_ProtectedPaths[i].Path) != NULL) {
            ACCESS_MASK desiredAccess = Data->Iopb->Parameters.Create.SecurityContext->DesiredAccess;
            ULONG disposition = (Data->Iopb->Parameters.Create.Options >> 24) & 0x000000ff;

            // 凡包含寫入、附加、覆寫、替換或刪除意圖 -> 核心層直接回傳 ACCESS_DENIED
            if ((desiredAccess & (FILE_WRITE_DATA | FILE_APPEND_DATA | DELETE | GENERIC_WRITE)) ||
                (disposition == FILE_SUPERSEDE || disposition == FILE_OVERWRITE || disposition == FILE_OVERWRITE_IF)) {
                
                FltReleaseFileNameInformation(nameInfo);
                Data->IoStatus.Status = STATUS_ACCESS_DENIED;
                Data->IoStatus.Information = 0;
                return FLT_PREOP_COMPLETE;
            }
        }
    }

    FltReleaseFileNameInformation(nameInfo);
    return FLT_PREOP_SUCCESS_NO_CALLBACK;
}

// 阻斷寫入與改名/刪除 (IRP_MJ_WRITE / IRP_MJ_SET_INFORMATION)
FLT_PREOP_CALLBACK_STATUS AntiTamperPreWriteOrSetInfo(
    PFLT_CALLBACK_DATA Data,
    PCFLT_RELATED_OBJECTS FltObjects,
    PVOID* CompletionContext
) {
    UNREFERENCED_PARAMETER(FltObjects);
    UNREFERENCED_PARAMETER(CompletionContext);

    PEPROCESS RequestorProcess = FltGetRequestorProcess(Data);
    HANDLE RequestorPid = RequestorProcess ? PsGetProcessId(RequestorProcess) : 0;

    // 守護進程放行
    if (g_GuardianPid != 0 && (ULONG_PTR)RequestorPid == g_GuardianPid) {
        return FLT_PREOP_SUCCESS_NO_CALLBACK;
    }

    // 阻斷未受信任進程的 I/O 寫入或截斷改名
    Data->IoStatus.Status = STATUS_ACCESS_DENIED;
    Data->IoStatus.Information = 0;
    return FLT_PREOP_COMPLETE;
}

// ================= 3. 驅動註冊結構與卸載 =================
CONST FLT_OPERATION_REGISTRATION Callbacks[] = {
    { IRP_MJ_CREATE, 0, AntiTamperPreCreate, NULL },
    { IRP_MJ_WRITE, 0, AntiTamperPreWriteOrSetInfo, NULL },
    { IRP_MJ_SET_INFORMATION, 0, AntiTamperPreWriteOrSetInfo, NULL },
    { IRP_MJ_OPERATION_END }
};

CONST FLT_REGISTRATION FilterRegistration = {
    sizeof(FLT_REGISTRATION),
    FLT_REGISTRATION_VERSION,
    0,
    NULL,
    Callbacks,
    NULL,
    NULL,
    NULL,
    NULL,
    NULL,
    NULL,
    NULL,
    NULL
};

NTSTATUS DriverEntry(PDRIVER_OBJECT DriverObject, PUNICODE_STRING RegistryPath) {
    UNREFERENCED_PARAMETER(RegistryPath);
    NTSTATUS status;

    // 註冊 Minifilter
    status = FltRegisterFilter(DriverObject, &FilterRegistration, &g_FilterHandle);
    if (NT_SUCCESS(status)) {
        status = FltStartFiltering(g_FilterHandle);
    }

    // 註冊 ObRegisterCallbacks 進程控制代碼自衛防護
    OB_OPERATION_REGISTRATION opReg = {
        PsProcessType,
        OB_OPERATION_HANDLE_CREATE | OB_OPERATION_HANDLE_DUPLICATE,
        AntiTamperProcessPreCallback,
        NULL
    };

    OB_CALLBACK_REGISTRATION cbReg = {
        OB_FLT_REGISTRATION_VERSION,
        1,
        RTL_CONSTANT_STRING(L"385201"),
        NULL,
        &opReg
    };

    ObRegisterCallbacks(&cbReg, &g_ObRegistrationHandle);
    return STATUS_SUCCESS;
}

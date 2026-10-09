// Copyright (C) Microsoft Corporation. All rights reserved.

#include "driver.h"
#include "device.tmh"
#include "apple1902_validation.h"
#include "out_pipe_policy.h"

#define MAX_HOST_MTU_SIZE               (9014)
#define MAX_HOST_TX_NTB_DATAGRAM_COUNT  (UINT16) (16)
#define PENDING_BULK_IN_READS           (8)

// Diagnostics only: true for the 1st, 2nd, 4th, 8th... occurrence so a
// sustained failure cannot flood the debugger.
static
bool
ShouldLogOccurrence(
    _In_ LONG count
)
{
    return count > 0 && (count & (count - 1)) == 0;
}

static_assert((unsigned)STATUS_CANCELLED == Apple1902::Status::Cancelled, "status mismatch");
static_assert((unsigned)STATUS_IO_TIMEOUT == Apple1902::Status::IoTimeout, "status mismatch");
static_assert((unsigned)STATUS_NO_SUCH_DEVICE == Apple1902::Status::NoSuchDevice, "status mismatch");
static_assert((unsigned)STATUS_DEVICE_NOT_CONNECTED == Apple1902::Status::DeviceNotConnected, "status mismatch");
static_assert((unsigned)STATUS_DEVICE_REMOVED == Apple1902::Status::DeviceRemoved, "status mismatch");
static_assert((unsigned)STATUS_DELETE_PENDING == Apple1902::Status::DeletePending, "status mismatch");
static_assert((unsigned)STATUS_DEVICE_DOES_NOT_EXIST == Apple1902::Status::DeviceDoesNotExist, "status mismatch");
static_assert((unsigned)STATUS_DEVICE_POWERED_OFF == Apple1902::Status::DevicePoweredOff, "status mismatch");
static_assert((unsigned)USBD_STATUS_XACT_ERROR == Apple1902::Status::UsbdXactError, "status mismatch");
static_assert((unsigned)USBD_STATUS_DEVICE_GONE == Apple1902::Status::UsbdDeviceGone, "status mismatch");

// KeQueryInterruptTime units (100 ns) to whole milliseconds.
static
ULONG64
ElapsedMs(
    _In_ ULONG64 from,
    _In_ ULONG64 to
)
{
    return (to - from) / 10000;
}

const USBNCM_DEVICE_EVENT_CALLBACKS UsbNcmHostDevice::s_NcmDeviceCallbacks =
{
    sizeof(USBNCM_DEVICE_EVENT_CALLBACKS),
    UsbNcmHostDevice::StartReceive,
    UsbNcmHostDevice::StopReceive,
    UsbNcmHostDevice::StartTransmit,
    UsbNcmHostDevice::StopTransmit,
    UsbNcmHostDevice::TransmitFrames
};

_IRQL_requires_max_(DISPATCH_LEVEL)
NTSTATUS
StartPipe(
    _In_ WDFUSBPIPE pipe
)
{
    // Guard against NULL pipe
    if (pipe == nullptr)
    {
        return STATUS_SUCCESS;
    }
    
    WDFIOTARGET wdfIotarget;

    wdfIotarget = WdfUsbTargetPipeGetIoTarget(pipe);
    return WdfIoTargetStart(wdfIotarget);
}

_IRQL_requires_max_(PASSIVE_LEVEL)
void
StopPipe(
    _In_ WDFUSBPIPE pipe
)
{
    // Guard against NULL pipe
    if (pipe == nullptr)
    {
        return;
    }
    
    WDFIOTARGET wdfIotarget;

    wdfIotarget = WdfUsbTargetPipeGetIoTarget(pipe);
    WdfIoTargetStop(wdfIotarget, WdfIoTargetCancelSentIo);
}

PAGEDX
_Use_decl_annotations_
NTSTATUS
UsbNcmHostDevice::SetDeviceFriendlyName(
    void
)
{
    // Use the package's stable adapter identity, not optional Mac firmware
    // strings. WdfDeviceAssignProperty copies the null-terminated value;
    // there is no retained allocation and no USB request for display naming.
    WCHAR friendlyName[] = L"Apple USB NCM Network Adapter";
    WDF_DEVICE_PROPERTY_DATA propertyData;
    WDF_DEVICE_PROPERTY_DATA_INIT(&propertyData, &DEVPKEY_Device_FriendlyName);
    propertyData.Flags = PLUGPLAY_PROPERTY_PERSISTENT;

    NCM_RETURN_IF_NOT_NT_SUCCESS_MSG(
        WdfDeviceAssignProperty(
            m_WdfDevice,
            &propertyData,
            DEVPROP_TYPE_STRING,
            sizeof(friendlyName),
            friendlyName),
        "Friendly name assignment failed");

    return STATUS_SUCCESS;
}

PAGEDX
_Use_decl_annotations_
NTSTATUS
UsbNcmHostDevice::InitializeDevice(
    void
)
{
    WDF_USB_DEVICE_INFORMATION deviceInfo;
    WDF_USB_DEVICE_CREATE_CONFIG createParams;
    NTSTATUS status;

    PAGED_CODE();

    // PrepareHardware may run again without destroying the WDFDEVICE. Its
    // USB target remains valid across ReleaseHardware; do not replace it and
    // leak the previous target (KMDF UsbDeviceCreateTarget contract).
    if (m_WdfUsbTargetDevice == nullptr)
    {
        WDF_USB_DEVICE_CREATE_CONFIG_INIT(
            &createParams,
            USBD_CLIENT_CONTRACT_VERSION_602);

        status = WdfUsbTargetDeviceCreateWithParameters(
            m_WdfDevice,
            &createParams,
            WDF_NO_OBJECT_ATTRIBUTES,
            &m_WdfUsbTargetDevice);
        if (!NT_SUCCESS(status))
        {
            DbgPrint("USBNCM: WdfUsbTargetDeviceCreateWithParameters FAILED 0x%08X\n", status);
            return status;
        }
    }

    // Independent experiment: only the 1902 composite parent is supported.
    USB_DEVICE_DESCRIPTOR deviceDescriptor;
    WdfUsbTargetDeviceGetDeviceDescriptor(m_WdfUsbTargetDevice, &deviceDescriptor);
    
    if (!Apple1902::IsSupported(deviceDescriptor.idVendor, deviceDescriptor.idProduct))
    {
        return STATUS_NOT_SUPPORTED;
    }

    // Check what interfaces Windows gave us
    BYTE numInterfaces = WdfUsbTargetDeviceGetNumInterfaces(m_WdfUsbTargetDevice);
    if (numInterfaces != 4)
    {
        DbgPrint("Sideline1902: require composite parent with 4 interfaces, got %u\n", numInterfaces);
        return STATUS_DEVICE_CONFIGURATION_ERROR;
    }

    BOOLEAN hasControlInterface = FALSE;
    BOOLEAN hasDataInterface = FALSE;
    
    // For Apple devices with composite parent match, we should get ALL interfaces
    // Look for the FIRST NCM pair: Interface 0 (control) + Interface 1 (data)
    for (BYTE i = 0; i < numInterfaces; i++)
    {
        WDFUSBINTERFACE usbInterface = WdfUsbTargetDeviceGetInterface(m_WdfUsbTargetDevice, i);
        USB_INTERFACE_DESCRIPTOR ifDesc;
        WdfUsbInterfaceGetDescriptor(usbInterface, 0, &ifDesc);
        
        BYTE ifNum = WdfUsbInterfaceGetInterfaceNumber(usbInterface);
        // For Apple composite device: Use interface 0 (control) and interface 1 (data)
        // (The device also has interface 2+3 as a second NCM pair, but we only use the first)
        if (ifNum == 0 && ifDesc.bInterfaceClass == 0x02 && ifDesc.bInterfaceSubClass == 0x0D)
        {
            if (hasControlInterface) return STATUS_DEVICE_CONFIGURATION_ERROR;
            hasControlInterface = TRUE;
            m_ControlInterface = usbInterface;
        }
        else if (ifNum == 1 && ifDesc.bInterfaceClass == 0x0A)
        {
            if (hasDataInterface) return STATUS_DEVICE_CONFIGURATION_ERROR;
            hasDataInterface = TRUE;
            m_DataInterface = usbInterface;
        }
    }

    if (!hasControlInterface || !hasDataInterface)
    {
        DbgPrint("Sideline1902: missing control/data pair\n");
        return STATUS_DEVICE_CONFIGURATION_ERROR;
    }

    // Standard NCM path - we have both interfaces
    
    // Ignore any error if we failed to set PnP FriendlyName
    (void) SetDeviceFriendlyName();

    WDF_USB_DEVICE_INFORMATION_INIT(&deviceInfo);

    status = WdfUsbTargetDeviceRetrieveInformation(
        m_WdfUsbTargetDevice,
        &deviceInfo);
    if (!NT_SUCCESS(status))
    {
        DbgPrint("USBNCM: WdfUsbTargetDeviceRetrieveInformation FAILED 0x%08X\n", status);
        return status;
    }

    status = SelectConfiguration();
    if (!NT_SUCCESS(status))
    {
        DbgPrint("USBNCM: SelectConfiguration FAILED 0x%08X\n", status);
        return status;
    }

    status = SelectSetting();
    if (!NT_SUCCESS(status))
    {
        DbgPrint("USBNCM: SelectSetting FAILED 0x%08X\n", status);
        return status;
    }

    status = RetrieveDataBulkPipes();
    if (!NT_SUCCESS(status))
    {
        DbgPrint("USBNCM: RetrieveDataBulkPipes FAILED 0x%08X\n", status);
        return status;
    }

    // Final validation
    if (!m_DataBulkInPipe || !m_DataBulkOutPipe)
    {
        DbgPrint("USBNCM: Missing bulk pipes - cannot function\n");
        return STATUS_DEVICE_HARDWARE_ERROR;
    }

    DbgPrint("USBNCM: InitializeDevice SUCCESS\n");
    return STATUS_SUCCESS;
}

PAGEDX
_Use_decl_annotations_
NTSTATUS
UsbNcmHostDevice::CreateAdapter(
    void
)
{
    PAGED_CODE();

    USBNCM_ADAPTER_PARAMETERS parameters =
    {
        m_Use32BitNtb,
        m_MacAddress,
        m_MaxDatagramSize,
        m_NtbParamters.wNtbOutMaxDatagrams > 0
            ? m_NtbParamters.wNtbOutMaxDatagrams
            : MAX_HOST_TX_NTB_DATAGRAM_COUNT,
        m_NtbParamters.dwNtbOutMaxSize,
        m_NtbParamters.wNdpOutAlignment,
        m_NtbParamters.wNdpOutDivisor,
        m_NtbParamters.wNdpOutPayloadRemainder,
    };

    NCM_RETURN_IF_NOT_NT_SUCCESS(
        UsbNcmAdapterCreate(
            m_WdfDevice,
            &parameters,
            &UsbNcmHostDevice::s_NcmDeviceCallbacks,
            &m_NetAdapter,
            &m_NcmAdapterCallbacks));

    return STATUS_SUCCESS;
}

PAGEDX
_Use_decl_annotations_
void
UsbNcmHostDevice::DestroyAdapter(
    void
)
{
    PAGED_CODE();

    if (m_NetAdapter != nullptr)
    {
        UsbNcmAdapterDestory(m_NetAdapter);
        m_NetAdapter = nullptr;
    }
    m_NcmAdapterCallbacks = nullptr;
}

PAGEDX
_Use_decl_annotations_
NTSTATUS
UsbNcmHostDevice::RequestClassSpecificControlTransfer(
    UINT8 request,
    WDF_USB_BMREQUEST_DIRECTION direction,
    WDF_USB_BMREQUEST_RECIPIENT recipient,
    UINT16 value,
    PWDF_MEMORY_DESCRIPTOR memoryDescriptor,
    PULONG bytesTransferred
)
{
    WDF_USB_CONTROL_SETUP_PACKET controlSetupPacket;
    WDF_REQUEST_SEND_OPTIONS sendOptions;

    PAGED_CODE();

    WDF_USB_CONTROL_SETUP_PACKET_INIT_CLASS(
        &controlSetupPacket,
        direction,
        recipient,
        request,
        value,
        WdfUsbInterfaceGetInterfaceNumber(m_ControlInterface));

    WDF_REQUEST_SEND_OPTIONS_INIT(&sendOptions, 0);

    NCM_RETURN_IF_NOT_NT_SUCCESS_MSG(
        WdfUsbTargetDeviceSendControlTransferSynchronously(
            m_WdfUsbTargetDevice,
            WDF_NO_HANDLE,
            &sendOptions,
            &controlSetupPacket,
            memoryDescriptor,
            bytesTransferred),
        "WdfUsbTargetDeviceSendControlTransferSynchronously failed");

    return STATUS_SUCCESS;
}

PAGEDX
_Use_decl_annotations_
NTSTATUS
UsbNcmHostDevice::SelectConfiguration(
    void
)
{
    WDF_OBJECT_ATTRIBUTES objectAttribs;

    PAGED_CODE();

    NTSTATUS status = STATUS_SUCCESS;

    // Get configuration descriptor
    PUSB_CONFIGURATION_DESCRIPTOR pDescriptors = NULL;
    USHORT sizeDescriptors = 0;
    WDFMEMORY descriptorMemory;

    status = WdfUsbTargetDeviceRetrieveConfigDescriptor(
        m_WdfUsbTargetDevice,
        NULL,
        &sizeDescriptors);

    NCM_RETURN_NT_STATUS_IF_FALSE_MSG(
        status == STATUS_BUFFER_TOO_SMALL,
        status,
        "WdfUsbTargetDeviceRetrieveConfigDescriptor failed");

    WDF_OBJECT_ATTRIBUTES_INIT(&objectAttribs);
    objectAttribs.ParentObject = m_WdfDevice;

    NCM_RETURN_IF_NOT_NT_SUCCESS_MSG(
        WdfMemoryCreate(
            &objectAttribs,
            NonPagedPoolNx,
            0,
            sizeDescriptors,
            &descriptorMemory,
            (PVOID*) &pDescriptors),
        "WdfMemoryCreate failed");

    RtlZeroMemory(pDescriptors, sizeDescriptors);

    // Only the parsed result is kept; release the copy before any other exit
    // so repeated PrepareHardware does not accumulate WDFDEVICE children.
    Apple1902::Configuration validated = {};
    bool parsed = false;
    status = WdfUsbTargetDeviceRetrieveConfigDescriptor(
        m_WdfUsbTargetDevice,
        pDescriptors,
        &sizeDescriptors);
    if (NT_SUCCESS(status))
    {
        parsed = Apple1902::ParseConfiguration((const unsigned char*)pDescriptors, sizeDescriptors, validated);
    }

    WdfObjectDelete(descriptorMemory);
    pDescriptors = nullptr;

    NCM_RETURN_IF_NOT_NT_SUCCESS_MSG(status, "WdfUsbTargetDeviceRetrieveConfigDescriptor failed");

    if (!parsed)
    {
        DbgPrint("Sideline1902: invalid or unsupported configuration descriptor\n");
        return STATUS_DEVICE_CONFIGURATION_ERROR;
    }

    // Verify data interface has 2 alternate settings
    BYTE numSettings = WdfUsbInterfaceGetNumSettings(m_DataInterface);
    if (numSettings != 2)
    {
        DbgPrint("USBNCM: ERROR - Data interface needs 2 alt settings, has %d\n", numSettings);
        return STATUS_DEVICE_HARDWARE_ERROR;
    }

    // Keep setting storage alive until the synchronous WDF call returns.
    WDF_USB_DEVICE_SELECT_CONFIG_PARAMS configParams;
    BYTE numInterfaces = WdfUsbTargetDeviceGetNumInterfaces(m_WdfUsbTargetDevice);
    WDF_USB_INTERFACE_SETTING_PAIR settingPairs[4] = {};
    if (numInterfaces != ARRAYSIZE(settingPairs)) return STATUS_DEVICE_CONFIGURATION_ERROR;
    for (BYTE i = 0; i < numInterfaces; ++i)
    {
        WDFUSBINTERFACE usbInterface = WdfUsbTargetDeviceGetInterface(m_WdfUsbTargetDevice, i);
        BYTE number = WdfUsbInterfaceGetInterfaceNumber(usbInterface);
        if (number >= ARRAYSIZE(settingPairs) || settingPairs[number].UsbInterface != nullptr)
            return STATUS_DEVICE_CONFIGURATION_ERROR;
        settingPairs[number].UsbInterface = usbInterface;
        settingPairs[number].SettingIndex = 0;
    }
    WDF_USB_DEVICE_SELECT_CONFIG_PARAMS_INIT_MULTIPLE_INTERFACES(
        &configParams, ARRAYSIZE(settingPairs), settingPairs);

    // SelectConfig deletes the previous pipe objects. The PnP/power path
    // has quiesced them; clear cached handles before a fallible reconfigure
    // so failure cleanup cannot stop an already deleted pipe.
    m_DataBulkInPipe = nullptr;
    m_DataBulkOutPipe = nullptr;
    m_DataBulkOutPipeMaximumPacketSize = 0;

    status = WdfUsbTargetDeviceSelectConfig(
        m_WdfUsbTargetDevice,
        WDF_NO_OBJECT_ATTRIBUTES,
        &configParams);
    if (!NT_SUCCESS(status))
    {
        DbgPrint("USBNCM: SelectConfig FAILED 0x%08X\n", status);
        return status;
    }

    // Query MTU
    m_MaxDatagramSize = min(validated.mtu, MAX_HOST_MTU_SIZE);

    // Query MAC address
    WCHAR strMacAddress[12] = {};
    USHORT strMacAddressLength = ARRAYSIZE(strMacAddress);

    status = WdfUsbTargetDeviceQueryString(
        m_WdfUsbTargetDevice,
        NULL,
        NULL,
        strMacAddress,
        &strMacAddressLength,
        validated.macIndex,
        0x0409);
    if (!NT_SUCCESS(status))
    {
        DbgPrint("USBNCM: Failed to get MAC address string 0x%08X\n", status);
        return status;
    }

    if (!Apple1902::ParseMac(strMacAddress, strMacAddressLength, m_MacAddress))
    {
        DbgPrint("Sideline1902: invalid MAC string\n");
        return STATUS_DEVICE_CONFIGURATION_ERROR;
    }

    // Get NTB parameters
    WDF_MEMORY_DESCRIPTOR memoryDescriptor;
    WDF_MEMORY_DESCRIPTOR_INIT_BUFFER(
        &memoryDescriptor,
        &m_NtbParamters,
        sizeof(m_NtbParamters));

    ULONG transferred = 0;
    RtlZeroMemory(&m_NtbParamters, sizeof(m_NtbParamters));
    status = RequestClassSpecificControlTransfer(
        USB_REQUEST_GET_NTB_PARAMETERS,
        BmRequestDeviceToHost,
        BmRequestToInterface,
        0,
        &memoryDescriptor,
        &transferred);
    if (!NT_SUCCESS(status))
    {
        DbgPrint("USBNCM: GET_NTB_PARAMETERS failed 0x%08X\n", status);
        return status;
    }

    // NTB 16 must be supported
    if (!Apple1902::ValidateNtb((const unsigned char*)&m_NtbParamters, transferred, m_MaxDatagramSize))
    {
        DbgPrint("Sideline1902: invalid/unsupported NTB parameters, transferred=%lu\n", transferred);
        return STATUS_DEVICE_CONFIGURATION_ERROR;
    }

    // Recompute for this negotiation, including repeated PrepareHardware.
    // Do not retain TRUE from a previous configuration that supported NTB32.
    m_Use32BitNtb = (m_NtbParamters.bmNtbFormatsSupported & 0x2) != 0;

    m_HostSelectedNtbInMaxSize = Apple1902::SelectNtbInMaxSize(
        m_NtbParamters.dwNtbInMaxSize,
        m_Use32BitNtb);

    return STATUS_SUCCESS;
}

PAGEDX
_Use_decl_annotations_
NTSTATUS
UsbNcmHostDevice::SelectSetting(
    void
)
{
    NTSTATUS status;
    
    PAGED_CODE();

    // 1. Data interface at Setting 0
    WDF_USB_INTERFACE_SELECT_SETTING_PARAMS settingParams;
    WDF_USB_INTERFACE_SELECT_SETTING_PARAMS_INIT_SETTING(&settingParams, 0);

    // Changing the alternate setting invalidates the old data pipe objects.
    // RetrieveDataBulkPipes installs fresh handles only after success.
    m_DataBulkInPipe = nullptr;
    m_DataBulkOutPipe = nullptr;
    m_DataBulkOutPipeMaximumPacketSize = 0;

    status = WdfUsbInterfaceSelectSetting(m_DataInterface, WDF_NO_OBJECT_ATTRIBUTES, &settingParams);
    if (!NT_SUCCESS(status))
    {
        DbgPrint("USBNCM: SelectSetting(0) FAILED 0x%08X\n", status);
        return status;
    }

    // 2. Config NTB
    if (m_Use32BitNtb)
    {
        status = RequestClassSpecificControlTransfer(
            USB_REQUEST_SET_NTB_FORMAT,
            BmRequestHostToDevice,
            BmRequestToInterface,
            1,
            nullptr);
        if (!NT_SUCCESS(status))
        {
            DbgPrint("Sideline1902: SET_NTB_FORMAT failed 0x%08X\n", status);
            return status;
        }
    }

    if (m_HostSelectedNtbInMaxSize < m_NtbParamters.dwNtbInMaxSize)
    {
        WDF_MEMORY_DESCRIPTOR memoryDescriptor;
        WDF_MEMORY_DESCRIPTOR_INIT_BUFFER(
            &memoryDescriptor,
            (PVOID)&m_HostSelectedNtbInMaxSize,
            sizeof(m_HostSelectedNtbInMaxSize));

        status = RequestClassSpecificControlTransfer(
            USB_REQUEST_SET_NTB_INPUT_SIZE,
            BmRequestHostToDevice,
            BmRequestToInterface,
            0,
            &memoryDescriptor);
        if (!NT_SUCCESS(status))
        {
            DbgPrint("Sideline1902: SET_NTB_INPUT_SIZE failed 0x%08X\n", status);
            return status;
        }
    }

    // 3. Data interface at Setting 1
    WDF_USB_INTERFACE_SELECT_SETTING_PARAMS_INIT_SETTING(&settingParams, 1);

    status = WdfUsbInterfaceSelectSetting(m_DataInterface, WDF_NO_OBJECT_ATTRIBUTES, &settingParams);
    if (!NT_SUCCESS(status))
    {
        DbgPrint("USBNCM: SelectSetting(1) FAILED 0x%08X\n", status);
        return status;
    }

    return STATUS_SUCCESS;
}

PAGEDX
_Use_decl_annotations_
NTSTATUS
UsbNcmHostDevice::RetrieveDataBulkPipes(
    void
)
{
    PAGED_CODE();

    m_DataBulkInPipe = nullptr;
    m_DataBulkOutPipe = nullptr;
    m_DataBulkOutPipeMaximumPacketSize = 0;

    NCM_RETURN_NT_STATUS_IF_FALSE_MSG(
        WdfUsbInterfaceGetNumConfiguredPipes(m_DataInterface) == 2,
        STATUS_DEVICE_HARDWARE_ERROR,
        "Bad NCM data interface");

    for (UCHAR pipeIndex = 0; pipeIndex < 2; pipeIndex++)
    {
        WDF_USB_PIPE_INFORMATION pipeInfo;
        WDF_USB_PIPE_INFORMATION_INIT(&pipeInfo);

        WDFUSBPIPE pipe = WdfUsbInterfaceGetConfiguredPipe(
            m_DataInterface,
            pipeIndex,
            &pipeInfo);

        NCM_RETURN_NT_STATUS_IF_FALSE_MSG(
            pipeInfo.PipeType == WdfUsbPipeTypeBulk && pipeInfo.MaximumPacketSize != 0,
            STATUS_DEVICE_HARDWARE_ERROR,
            "Bad NCM data pipe type");

        WdfUsbTargetPipeSetNoMaximumPacketSizeCheck(pipe);

        if (WdfUsbTargetPipeIsInEndpoint(pipe))
        {
            if (m_DataBulkInPipe) return STATUS_DEVICE_CONFIGURATION_ERROR;
            m_DataBulkInPipe = pipe;
        }
        else if (WdfUsbTargetPipeIsOutEndpoint(pipe))
        {
            if (m_DataBulkOutPipe) return STATUS_DEVICE_CONFIGURATION_ERROR;
            m_DataBulkOutPipeMaximumPacketSize = pipeInfo.MaximumPacketSize;
            m_DataBulkOutPipe = pipe;
        }
    }

    if (!m_DataBulkInPipe || !m_DataBulkOutPipe || !m_DataBulkOutPipeMaximumPacketSize)
        return STATUS_DEVICE_CONFIGURATION_ERROR;

    WDF_USB_CONTINUOUS_READER_CONFIG readerConfig;
    WDF_USB_CONTINUOUS_READER_CONFIG_INIT(
        &readerConfig,
        UsbNcmHostDevice::DataBulkInPipeReadCompletetionRoutine,
        this,
        m_HostSelectedNtbInMaxSize);

    readerConfig.HeaderLength = 0;
    readerConfig.NumPendingReads = PENDING_BULK_IN_READS;
    readerConfig.EvtUsbTargetPipeReadersFailed = UsbNcmHostDevice::DataBulkInPipeReadersFailed;

    NCM_RETURN_IF_NOT_NT_SUCCESS_MSG(
        WdfUsbTargetPipeConfigContinuousReader(
            m_DataBulkInPipe,
            &readerConfig),
        "WdfUsbTargetPipeConfigContinuousReader failed for bulkin pipe");

    return STATUS_SUCCESS;
}

_IRQL_requires_(PASSIVE_LEVEL)
static
Apple1902::Capability
QueryConnectionCapability(
    _In_ WDFUSBDEVICE usbDevice,
    _In_ const GUID * capability
)
{
    const NTSTATUS status = WdfUsbTargetDeviceQueryUsbCapability(
        usbDevice,
        capability,
        0,
        nullptr,
        nullptr);

    if (NT_SUCCESS(status))
    {
        return Apple1902::Capability::Supported;
    }

    return status == STATUS_NOT_SUPPORTED
        ? Apple1902::Capability::NotSupported
        : Apple1902::Capability::QueryFailed;
}

PAGEDX
_Use_decl_annotations_
NTSTATUS
UsbNcmHostDevice::EnterWorkingState(
    WDF_POWER_DEVICE_STATE previousState
)
{
    PAGED_CODE();

    // A new D0 session: the OUT recovery budget resets here and nowhere else.
    BeginD0Session();

    if (previousState != WdfPowerDeviceD3Final)
    {
        NCM_RETURN_IF_NOT_NT_SUCCESS(SelectSetting());
        NCM_RETURN_IF_NOT_NT_SUCCESS(RetrieveDataBulkPipes());
    }

    // The 1902 control interfaces have no notification endpoint
    // (ParseConfiguration enforces this), so force link up here.
    if (m_NcmAdapterCallbacks != nullptr)
    {
        static_assert(Apple1902::UnknownLinkSpeed == NDIS_LINK_SPEED_UNKNOWN,
                      "unknown link speed must match NDIS");

        const ULONG64 linkSpeed = Apple1902::LinkSpeedFromCapabilities(
            QueryConnectionCapability(
                m_WdfUsbTargetDevice,
                &GUID_USB_CAPABILITY_DEVICE_CONNECTION_SUPER_SPEED_COMPATIBLE),
            QueryConnectionCapability(
                m_WdfUsbTargetDevice,
                &GUID_USB_CAPABILITY_DEVICE_CONNECTION_HIGH_SPEED_COMPATIBLE));
        DbgPrint("USBNCM: Link speed %I64u bps\n", linkSpeed);

        // Record the speed first so the link-up indication carries it.
        m_NcmAdapterCallbacks->EvtUsbNcmAdapterSetLinkSpeed(m_NetAdapter, linkSpeed, linkSpeed);
        m_NcmAdapterCallbacks->EvtUsbNcmAdapterSetLinkState(m_NetAdapter, TRUE);
    }

    return STATUS_SUCCESS;
}

PAGEDX
_Use_decl_annotations_
NTSTATUS
UsbNcmHostDevice::LeaveWorkingState(
    void
)
{
    PAGED_CODE();

    // Covers partial power-up and removal as well as normal queue shutdown.
    StopReceive(m_WdfDevice);
    StopTransmit(m_WdfDevice);
    return STATUS_SUCCESS;
}

_Use_decl_annotations_
VOID
UsbNcmHostDevice::DataBulkInPipeReadCompletetionRoutine(
    WDFUSBPIPE,
    WDFMEMORY memory,
    size_t numBytesTransferred,
    WDFCONTEXT context
)
{
    UsbNcmHostDevice* hostDevice = (UsbNcmHostDevice *)context;

    if (numBytesTransferred == 0 ||
        numBytesTransferred > hostDevice->m_HostSelectedNtbInMaxSize)
    {
        return;
    }

    hostDevice->m_NcmAdapterCallbacks->EvtUsbNcmAdapterNotifyReceive(
        hostDevice->m_NetAdapter,
        nullptr,
        numBytesTransferred,
        memory,
        WDF_NO_HANDLE);
}

PAGEDX
_Use_decl_annotations_
void
UsbNcmHostDevice::StartReceive(
    WDFDEVICE usbNcmWdfDevice
)
{
    UsbNcmHostDevice* hostDevice = NcmGetHostDeviceFromHandle(usbNcmWdfDevice);
    if (!hostDevice->IsRecoveryMode())
    {
        if (hostDevice->m_DataBulkInPipe != nullptr)
        {
            (void) StartPipe(hostDevice->m_DataBulkInPipe);
        }
        return;
    }

    WdfWaitLockAcquire(hostDevice->m_DataPathLock, nullptr);
    if (hostDevice->m_DataBulkInPipe != nullptr)
    {
        const NTSTATUS status = StartPipe(hostDevice->m_DataBulkInPipe);
        hostDevice->m_RxPipeRunning = NT_SUCCESS(status);
        if (!NT_SUCCESS(status))
        {
            DbgPrint("Sideline1902: IN pipe start failed 0x%08X\n", status);
            hostDevice->SetDataPathFailedLocked();
        }
        hostDevice->RestoreDataPathLinkLocked();
    }
    WdfWaitLockRelease(hostDevice->m_DataPathLock);
}

PAGEDX
_Use_decl_annotations_
void
UsbNcmHostDevice::StopReceive(
    WDFDEVICE usbNcmWdfDevice
)
{
    UsbNcmHostDevice* hostDevice = NcmGetHostDeviceFromHandle(usbNcmWdfDevice);
    if (!hostDevice->IsRecoveryMode())
    {
        if (hostDevice->m_DataBulkInPipe != nullptr)
        {
            StopPipe(hostDevice->m_DataBulkInPipe);
        }
        return;
    }

    // Stopping a continuous-reader pipe also waits for the framework's
    // reader work item; DataBulkInPipeReadersFailed takes no lock, so this
    // cannot wait on itself.
    // A queued work item then skips the IN pipe. D0Exit and adapter destroy
    // also run StopTransmit, which flushes the work item.
    WdfWaitLockAcquire(hostDevice->m_DataPathLock, nullptr);
    hostDevice->m_RxPipeRunning = FALSE;
    if (hostDevice->m_DataBulkInPipe != nullptr)
    {
        StopPipe(hostDevice->m_DataBulkInPipe);
    }
    WdfWaitLockRelease(hostDevice->m_DataPathLock);
}

PAGEDX
_Use_decl_annotations_
void
UsbNcmHostDevice::StartTransmit(
    WDFDEVICE usbNcmWdfDevice
)
{
    UsbNcmHostDevice* hostDevice = NcmGetHostDeviceFromHandle(usbNcmWdfDevice);
    if (!hostDevice->IsRecoveryMode())
    {
        if (hostDevice->m_DataBulkOutPipe != nullptr)
        {
            (void) StartPipe(hostDevice->m_DataBulkOutPipe);
        }
        return;
    }

    WdfWaitLockAcquire(hostDevice->m_DataPathLock, nullptr);
    if (hostDevice->m_DataBulkOutPipe != nullptr)
    {
        const NTSTATUS status = StartPipe(hostDevice->m_DataBulkOutPipe);
        if (NT_SUCCESS(status))
        {
            hostDevice->m_TxPipeRunning = TRUE;
            InterlockedExchange(&hostDevice->m_TxRecoveryEnabled, 1);
            hostDevice->OpenTxAdmissionLocked();
            hostDevice->RestoreDataPathLinkLocked();
        }
        else
        {
            // Not marked running; sends stay closed.
            DbgPrint("Sideline1902: OUT pipe start failed 0x%08X\n", status);
            hostDevice->SetDataPathFailedLocked();
        }
    }
    WdfWaitLockRelease(hostDevice->m_DataPathLock);
}

PAGEDX
_Use_decl_annotations_
void
UsbNcmHostDevice::StopTransmit(
    WDFDEVICE usbNcmWdfDevice
)
{
    UsbNcmHostDevice* hostDevice = NcmGetHostDeviceFromHandle(usbNcmWdfDevice);
    if (!hostDevice->IsRecoveryMode())
    {
        if (hostDevice->m_DataBulkOutPipe != nullptr)
        {
            StopPipe(hostDevice->m_DataBulkOutPipe);
        }
    }
    else
    {
        WdfWaitLockAcquire(hostDevice->m_DataPathLock, nullptr);
        InterlockedExchange(&hostDevice->m_TxRecoveryEnabled, 0);
        hostDevice->m_TxPipeRunning = FALSE;
        // A stopped target queues new sends instead of failing them.
        hostDevice->CloseTxAdmissionLocked();
        if (hostDevice->m_DataBulkOutPipe != nullptr)
        {
            StopPipe(hostDevice->m_DataBulkOutPipe);
        }
        // The DPC only enqueues work: it never takes this lock or waits.
        // Keeping the lock here serializes duplicate stops and prevents a
        // worker from rearming the timer while it is being drained.
        WdfTimerStop(hostDevice->m_OutRecoveryTimer, TRUE);
        if (InterlockedExchange(&hostDevice->m_TxRecoveryQueued, 0) != 0)
        {
            DbgPrint("Sideline1902: OUT pending recovery cancelled by stop; deferred %d, total attempts %I64u\n",
                     hostDevice->m_TxRecoveryDueTime != 0,
                     hostDevice->m_TxRecoveryAttempts);
        }
        hostDevice->m_TxRecoveryDueTime = 0;
        WdfWaitLockRelease(hostDevice->m_DataPathLock);

        // Outside the lock, which a queued work item needs. StopPipe
        // returned after every sent request's completion routine and
        // admission is closed and the timer is drained, so no OUT source
        // can enqueue the work item until a later StartTransmit. Runs for
        // a null pipe as well.
        WdfWorkItemFlush(hostDevice->m_DataPathWorkItem);
    }

    if (hostDevice->IsInstrumentationMode())
    {
        DbgPrint("Sideline1902: OUT stop: inflight %ld peak %ld ok %ld cancelled %ld "
                 "timeouts %ld failed %ld send-failed %ld rejected %ld\n",
                 InterlockedCompareExchange(&hostDevice->m_TxInflight, 0, 0),
                 InterlockedCompareExchange(&hostDevice->m_TxInflightPeak, 0, 0),
                 InterlockedCompareExchange(&hostDevice->m_TxSuccesses, 0, 0),
                 InterlockedCompareExchange(&hostDevice->m_TxCancellations, 0, 0),
                 InterlockedCompareExchange(&hostDevice->m_TxTimeouts, 0, 0),
                 InterlockedCompareExchange(&hostDevice->m_TxCompletionFailures, 0, 0),
                 InterlockedCompareExchange(&hostDevice->m_TxSendFailures, 0, 0),
                 InterlockedCompareExchange(&hostDevice->m_TxAdmissionRejects, 0, 0));
    }
}

_Use_decl_annotations_
BOOLEAN
UsbNcmHostDevice::DataBulkInPipeReadersFailed(
    WDFUSBPIPE pipe,
    NTSTATUS status,
    USBD_STATUS usbdStatus
)
{
    UsbNcmHostDevice * hostDevice = NcmGetHostDeviceFromHandle(
        WdfIoTargetGetDevice(WdfUsbTargetPipeGetIoTarget(pipe)));

    const LONG failures = InterlockedIncrement(&hostDevice->m_RxReadersFailures);
    if (ShouldLogOccurrence(failures))
    {
        DbgPrint("Sideline1902: RX readers failed #%ld status 0x%08X usbd 0x%08X\n",
                 failures, status, usbdStatus);
    }

    if (!hostDevice->IsRecoveryMode())
    {
        // Same as configuring no callback: KMDF resets the pipe (or the
        // device if its port is disabled) and restarts the readers.
        return TRUE;
    }

    // Recovery mode: the framework must not reset the IN pipe or the port
    // outside m_DataPathLock. Hand the failure to the data-path work item,
    // which stops, resets and restarts the IN pipe under that lock. No lock
    // and no target stop/start here: stopping this pipe waits for the very
    // work item that runs this callback.
    hostDevice->RequestInPipeRecovery(status, usbdStatus);
    return FALSE;
}

_Use_decl_annotations_
inline
void
UsbNcmHostDevice::TransmitFramesCompetion(
    WDFREQUEST,
    WDFIOTARGET target,
    PWDF_REQUEST_COMPLETION_PARAMS params,
    WDFCONTEXT context
)
{
    UsbNcmHostDevice* hostDevice = NcmGetHostDeviceFromHandle(WdfIoTargetGetDevice(target));

    const NTSTATUS status = params->IoStatus.Status;
    const USBD_STATUS usbdStatus = params->Parameters.Usb.Completion != nullptr
        ? params->Parameters.Usb.Completion->UsbdStatus
        : 0;
    const Apple1902::TxCompletion kind =
        Apple1902::ClassifyTxCompletion((unsigned)status, (unsigned)usbdStatus);

    if (kind == Apple1902::TxCompletion::Cancelled)
    {
        const LONG cancellations = InterlockedIncrement(&hostDevice->m_TxCancellations);
        if (ShouldLogOccurrence(cancellations))
        {
            DbgPrint("Sideline1902: TX cancelled (stop or cancel) #%ld usbd 0x%08X\n",
                     cancellations, usbdStatus);
        }
    }
    else if (kind == Apple1902::TxCompletion::TimedOut)
    {
        const LONG timeouts = InterlockedIncrement(&hostDevice->m_TxTimeouts);
        if (ShouldLogOccurrence(timeouts))
        {
            DbgPrint("Sideline1902: TX timed out (5 s send timeout) #%ld usbd 0x%08X\n",
                     timeouts, usbdStatus);
        }
    }
    else if (kind != Apple1902::TxCompletion::Success)
    {
        const LONG failures = InterlockedIncrement(&hostDevice->m_TxCompletionFailures);
        if (ShouldLogOccurrence(failures))
        {
            DbgPrint("Sideline1902: TX completion failed #%ld status 0x%08X usbd 0x%08X\n",
                     failures, status, usbdStatus);
        }
    }

    if (hostDevice->IsInstrumentationMode())
    {
        const LONG inflight = InterlockedDecrement(&hostDevice->m_TxInflight);
        if (kind == Apple1902::TxCompletion::Success)
        {
            InterlockedIncrement(&hostDevice->m_TxSuccesses);
            InterlockedExchange64(&hostDevice->m_TxLastSuccessTime, (LONG64)KeQueryInterruptTime());
        }
        else if (kind != Apple1902::TxCompletion::Cancelled &&
                 InterlockedCompareExchange(&hostDevice->m_TxFirstFailureLogged, 1, 0) == 0)
        {
            // With 0 successes the elapsed time is reported as 0.
            const LONG64 lastSuccess = InterlockedCompareExchange64(&hostDevice->m_TxLastSuccessTime, 0, 0);
            DbgPrint("Sideline1902: OUT first failure: status 0x%08X usbd 0x%08X inflight %ld, "
                     "successes %ld, last OUT success %I64u ms ago\n",
                     status, usbdStatus, inflight,
                     InterlockedCompareExchange(&hostDevice->m_TxSuccesses, 0, 0),
                     lastSuccess != 0 ? ElapsedMs((ULONG64)lastSuccess, KeQueryInterruptTime()) : 0);
        }
    }

    if (hostDevice->IsRecoveryMode())
    {
        if (kind == Apple1902::TxCompletion::PipeError)
        {
            hostDevice->RequestOutPipeRecovery(status, usbdStatus);
        }
        else if (kind == Apple1902::TxCompletion::Success)
        {
            // Every request sent before a restart was cancelled by its stop,
            // so this success is traffic offered after the restart.
            const LONG64 restart = InterlockedCompareExchange64(&hostDevice->m_TxRestartTime, 0, 0);
            if (restart != 0 &&
                InterlockedCompareExchange(&hostDevice->m_TxPostRestartSuccessLogged, 1, 0) == 0)
            {
                const ULONG64 now = KeQueryInterruptTime();
                const LONG64 firstSend = InterlockedCompareExchange64(&hostDevice->m_TxPostRestartFirstSend, 0, 0);
                DbgPrint("Sideline1902: OUT first success after pipe restart: +%I64u ms after restart, "
                         "+%I64u ms after the first send offered after it\n",
                         ElapsedMs((ULONG64)restart, now),
                         firstSend != 0 ? ElapsedMs((ULONG64)firstSend, now) : 0);
            }
        }
    }

    // Returns the buffer to the pool; it may be reused at once.
    hostDevice->m_NcmAdapterCallbacks->EvtUsbNcmAdapterNotifyTransmitCompletion(
        hostDevice->m_NetAdapter,
        (TX_BUFFER_REQUEST *)context);
}

_Use_decl_annotations_
NTSTATUS
UsbNcmHostDevice::TransmitFrames(
    WDFDEVICE usbNcmWdfDevice,
    TX_BUFFER_REQUEST * bufferRequest
)
{
    NTSTATUS status = STATUS_SUCCESS;
    UsbNcmHostDevice * hostDevice = NcmGetHostDeviceFromHandle(usbNcmWdfDevice);

    // Recovery mode only: the send section holds an admission reference,
    // refused while the pipe is not running or is being reset.
    const bool gated = hostDevice->IsRecoveryMode();
    if (gated && !ExAcquireRundownProtection(&hostDevice->m_TxAdmission))
    {
        const LONG rejects = InterlockedIncrement(&hostDevice->m_TxAdmissionRejects);
        if (ShouldLogOccurrence(rejects))
        {
            DbgPrint("Sideline1902: TX dropped, OUT pipe not running #%ld\n", rejects);
        }
        return STATUS_DEVICE_NOT_READY;
    }

    // Guard against NULL pipe
    if (hostDevice->m_DataBulkOutPipe == nullptr || hostDevice->m_DataBulkOutPipeMaximumPacketSize == 0)
    {
        if (gated)
        {
            ExReleaseRundownProtection(&hostDevice->m_TxAdmission);
        }
        return STATUS_DEVICE_NOT_READY;
    }

    NT_FRE_ASSERT(bufferRequest->TransferLength > 0);

    if (bufferRequest->TransferLength < bufferRequest->BufferLength &&
        bufferRequest->TransferLength % hostDevice->m_DataBulkOutPipeMaximumPacketSize == 0)
    {
        bufferRequest->Buffer[bufferRequest->TransferLength] = 0;
        bufferRequest->TransferLength++;
    }

    WdfRequestSetCompletionRoutine(
        bufferRequest->Request,
        UsbNcmHostDevice::TransmitFramesCompetion,
        bufferRequest);

    WDFMEMORY_OFFSET offset{ 0, bufferRequest->TransferLength };
    status = WdfUsbTargetPipeFormatRequestForWrite(
        hostDevice->m_DataBulkOutPipe,
        bufferRequest->Request,
        bufferRequest->BufferWdfMemory,
        &offset);

    if (NT_SUCCESS(status))
    {
        WDF_REQUEST_SEND_OPTIONS sendOptions = {};
        WDF_REQUEST_SEND_OPTIONS_INIT(&sendOptions, WDF_REQUEST_SEND_OPTION_TIMEOUT);
        WDF_REQUEST_SEND_OPTIONS_SET_TIMEOUT(&sendOptions, WDF_REL_TIMEOUT_IN_SEC(5));

        // The completion routine may run inline, before WdfRequestSend
        // returns, and return this buffer to the pool for reuse. Count it
        // first, and do not touch bufferRequest after a successful send.
        const bool counted = hostDevice->IsInstrumentationMode();
        if (counted)
        {
            const LONG inflight = InterlockedIncrement(&hostDevice->m_TxInflight);
            LONG peak = InterlockedCompareExchange(&hostDevice->m_TxInflightPeak, 0, 0);
            while (inflight > peak)
            {
                const LONG previous = InterlockedCompareExchange(
                    &hostDevice->m_TxInflightPeak, inflight, peak);
                if (previous == peak)
                {
                    break;
                }
                peak = previous;
            }
        }

        if (gated)
        {
            // The data-progress window after a restart starts at the first
            // send actually offered, not at the restart itself.
            const LONG64 restart = InterlockedCompareExchange64(&hostDevice->m_TxRestartTime, 0, 0);
            if (restart != 0 &&
                InterlockedCompareExchange64(&hostDevice->m_TxPostRestartFirstSend, 0, 0) == 0)
            {
                // Publish the timestamp atomically, not a separate claimed
                // flag: a competing sender can complete inline before this
                // thread resumes. Its completion must already see the time.
                const ULONG64 now = KeQueryInterruptTime();
                if (InterlockedCompareExchange64(&hostDevice->m_TxPostRestartFirstSend, (LONG64)now, 0) == 0)
                {
                    DbgPrint("Sideline1902: OUT first send offered after pipe restart: +%I64u ms\n",
                             ElapsedMs((ULONG64)restart, now));
                }
            }
        }

        if (!WdfRequestSend(
                bufferRequest->Request,
                WdfUsbTargetPipeGetIoTarget(hostDevice->m_DataBulkOutPipe), &sendOptions))
        {
            // Not sent, so no completion routine runs: undo the count; the
            // caller still owns the buffer.
            status = WdfRequestGetStatus(bufferRequest->Request);
            if (counted)
            {
                InterlockedDecrement(&hostDevice->m_TxInflight);
            }
        }
    }

    if (!NT_SUCCESS(status))
    {
        const LONG failures = InterlockedIncrement(&hostDevice->m_TxSendFailures);
        if (ShouldLogOccurrence(failures))
        {
            DbgPrint("Sideline1902: TX send failed #%ld status 0x%08X\n", failures, status);
        }
    }

    if (gated)
    {
        ExReleaseRundownProtection(&hostDevice->m_TxAdmission);
    }
    return status;
}

PAGEDX
_Use_decl_annotations_
void
UsbNcmHostDevice::InitializeDataPathControl(
    void
)
{
    PAGED_CODE();

    ULONG value = 0;
    bool found = false;
    WDFKEY key = nullptr;
    if (NT_SUCCESS(WdfDeviceOpenRegistryKey(
            m_WdfDevice,
            PLUGPLAY_REGKEY_DEVICE,
            KEY_READ,
            WDF_NO_OBJECT_ATTRIBUTES,
            &key)))
    {
        DECLARE_CONST_UNICODE_STRING(valueName, SIDELINE1902_DATA_PATH_DEBUG_VALUE);
        found = NT_SUCCESS(WdfRegistryQueryULong(key, &valueName, &value));
        WdfRegistryClose(key);
    }

    m_DataPathDebug = Apple1902::DataPathDebugFromRegistry(found, value);
    if (found && value != m_DataPathDebug)
    {
        DbgPrint("Sideline1902: data-path debug 0x%lX has unknown bits; using 0\n", value);
    }

    if (IsRecoveryMode())
    {
        WDF_OBJECT_ATTRIBUTES attributes;
        WDF_OBJECT_ATTRIBUTES_INIT(&attributes);
        attributes.ParentObject = m_WdfDevice;

        NTSTATUS status = WdfWaitLockCreate(&attributes, &m_DataPathLock);
        if (NT_SUCCESS(status))
        {
            WDF_WORKITEM_CONFIG config;
            WDF_WORKITEM_CONFIG_INIT(&config, UsbNcmHostDevice::DataPathRecoveryWorkItem);
            config.AutomaticSerialization = FALSE;
            status = WdfWorkItemCreate(&config, &attributes, &m_DataPathWorkItem);
        }

        if (NT_SUCCESS(status))
        {
            WDF_TIMER_CONFIG config;
            WDF_TIMER_CONFIG_INIT(&config, UsbNcmHostDevice::OutRecoveryTimer);
            // A nonblocking DPC: automatic device serialization could make
            // Stop's synchronous timer drain wait on a lifecycle callback.
            config.AutomaticSerialization = FALSE;
            attributes.ExecutionLevel = WdfExecutionLevelDispatch;
            status = WdfTimerCreate(&config, &attributes, &m_OutRecoveryTimer);
        }

        if (!NT_SUCCESS(status))
        {
            // All objects are parented to the device and go with it. None
            // was enqueued or armed before all allocations succeeded.
            m_DataPathLock = nullptr;
            m_DataPathWorkItem = nullptr;
            m_OutRecoveryTimer = nullptr;
            m_DataPathDebug &= ~Apple1902::DataPathOutPipeRecovery;
            DbgPrint("Sideline1902: data-path recovery setup failed 0x%08X; recovery off\n", status);
        }
        else
        {
            // Closed until a StartTransmit whose pipe start succeeds.
            ExInitializeRundownProtection(&m_TxAdmission);
            WdfWaitLockAcquire(m_DataPathLock, nullptr);
            m_TxAdmissionOpen = TRUE;
            CloseTxAdmissionLocked();
            WdfWaitLockRelease(m_DataPathLock);
        }
    }

    if (m_DataPathDebug != 0)
    {
        DbgPrint("Sideline1902: data-path debug 0x%lX: OUT instrumentation %d, pipe recovery %d\n",
                 m_DataPathDebug, IsInstrumentationMode(), IsRecoveryMode());
    }
}

PAGEDX
_Use_decl_annotations_
void
UsbNcmHostDevice::BeginD0Session(
    void
)
{
    PAGED_CODE();

    if (IsRecoveryMode())
    {
        // D0Exit stopped both pipes and flushed the work item before this.
        // Queue stop/start inside one D0 session does not come here.
        WdfWaitLockAcquire(m_DataPathLock, nullptr);
        m_DataPathLinkFailed = FALSE;
        m_TxRecoveryAttempts = 0;
        Apple1902::ResetOutRecoveryBudget(m_TxRecoveryBudget, KeQueryInterruptTime());
        DbgPrint("Sideline1902: OUT recovery credit: burst %u, refill %I64u ms, cooldown %I64u ms\n",
                 Apple1902::OutRecoveryCapacity, Apple1902::OutRecoveryRefill / 10000,
                 Apple1902::OutRecoveryCooldown / 10000);
        m_TxRecoveryDueTime = 0;
        InterlockedExchange64(&m_TxRestartTime, 0);
        WdfWaitLockRelease(m_DataPathLock);
    }

    if (IsInstrumentationMode())
    {
        InterlockedExchange(&m_TxFirstFailureLogged, 0);
    }
}

_Use_decl_annotations_
void
UsbNcmHostDevice::CloseTxAdmissionLocked(
    void
)
{
    if (m_TxAdmissionOpen)
    {
        // New ExAcquireRundownProtection calls fail from here on; this waits
        // for every TransmitFrames section that already holds a reference.
        // No spin lock is held, and the sections never take the wait lock.
        ExWaitForRundownProtectionRelease(&m_TxAdmission);
        m_TxAdmissionOpen = FALSE;
    }
}

_Use_decl_annotations_
void
UsbNcmHostDevice::OpenTxAdmissionLocked(
    void
)
{
    if (!m_TxAdmissionOpen)
    {
        ExReInitializeRundownProtection(&m_TxAdmission);
        m_TxAdmissionOpen = TRUE;
    }
}

_Use_decl_annotations_
void
UsbNcmHostDevice::RequestOutPipeRecovery(
    NTSTATUS status,
    USBD_STATUS usbdStatus
)
{
    // One OUT trigger at a time. The work item decides (running, budget,
    // cooldown) under the lock; an error while one is pending is counted.
    if (InterlockedCompareExchange(&m_TxRecoveryQueued, 1, 0) != 0)
    {
        const LONG coalesced = InterlockedIncrement(&m_TxRecoveryCoalesced);
        if (ShouldLogOccurrence(coalesced))
        {
            DbgPrint("Sideline1902: OUT recovery already pending; error not queued #%ld "
                     "status 0x%08X usbd 0x%08X\n", coalesced, status, usbdStatus);
        }
        return;
    }

    InterlockedExchange(&m_TxRecoveryTriggerStatus, status);
    InterlockedExchange(&m_TxRecoveryTriggerUsbdStatus, usbdStatus);
    WdfWorkItemEnqueue(m_DataPathWorkItem);
}

_Use_decl_annotations_
void
UsbNcmHostDevice::RequestInPipeRecovery(
    NTSTATUS status,
    USBD_STATUS usbdStatus
)
{
    // The readers stay cancelled until the work item restarts them, so a
    // second failure cannot arrive before this one is handled.
    InterlockedExchange(&m_RxRecoveryTriggerStatus, status);
    InterlockedExchange(&m_RxRecoveryTriggerUsbdStatus, usbdStatus);
    InterlockedExchange(&m_RxRecoveryPending, 1);
    WdfWorkItemEnqueue(m_DataPathWorkItem);
}

_Use_decl_annotations_
VOID
UsbNcmHostDevice::DataPathRecoveryWorkItem(
    WDFWORKITEM workItem
)
{
    NcmGetHostDeviceFromHandle((WDFDEVICE)WdfWorkItemGetParentObject(workItem))->RecoverDataPipes();
}

_Use_decl_annotations_
VOID
UsbNcmHostDevice::OutRecoveryTimer(
    WDFTIMER timer
)
{
    UsbNcmHostDevice * hostDevice = NcmGetHostDeviceFromHandle(
        (WDFDEVICE)WdfTimerGetParentObject(timer));

    // No lock, pipe access or wait on the DPC path. Stop first disables
    // this source, then waits for this callback, then flushes queued work.
    if (InterlockedCompareExchange(&hostDevice->m_TxRecoveryEnabled, 0, 0) != 0 &&
        InterlockedCompareExchange(&hostDevice->m_TxRecoveryQueued, 0, 0) != 0)
    {
        WdfWorkItemEnqueue(hostDevice->m_DataPathWorkItem);
    }
}

// Every stop, reset and start of either data pipe happens under
// m_DataPathLock, so recoveries never overlap each other or a queue or D0
// start/stop. In recovery mode the framework's own reader recovery (pipe
// reset, or device reset when the port is disabled) never runs, because
// DataBulkInPipeReadersFailed returns FALSE.
PAGEDX
_Use_decl_annotations_
void
UsbNcmHostDevice::SetDataPathFailedLocked(void)
{
    PAGED_CODE();
    if (!m_DataPathLinkFailed)
    {
        m_DataPathLinkFailed = TRUE;
        if (m_NcmAdapterCallbacks != nullptr)
        {
            m_NcmAdapterCallbacks->EvtUsbNcmAdapterSetLinkState(m_NetAdapter, FALSE);
        }
        DbgPrint("Sideline1902: terminal data-pipe failure; link disconnected (no PnP reset)\n");
    }
}

PAGEDX
_Use_decl_annotations_
void
UsbNcmHostDevice::RestoreDataPathLinkLocked(void)
{
    PAGED_CODE();
    // Queue starts, not packet success, restore the indication. Waiting for
    // a successful packet while disconnected could prevent that very send.
    // This is pipe readiness only; it does not prove delivery or repair PHY.
    if (m_DataPathLinkFailed && m_RxPipeRunning && m_TxPipeRunning)
    {
        m_DataPathLinkFailed = FALSE;
        if (m_NcmAdapterCallbacks != nullptr)
        {
            m_NcmAdapterCallbacks->EvtUsbNcmAdapterSetLinkState(m_NetAdapter, TRUE);
        }
        DbgPrint("Sideline1902: both data pipes restarted; link connected, delivery unverified\n");
    }
}

PAGEDX
_Use_decl_annotations_
void
UsbNcmHostDevice::RecoverDataPipes(
    void
)
{
    PAGED_CODE();

    WdfWaitLockAcquire(m_DataPathLock, nullptr);
    if (InterlockedExchange(&m_RxRecoveryPending, 0) != 0)
    {
        RecoverInPipeLocked();
    }
    if (InterlockedCompareExchange(&m_TxRecoveryQueued, 0, 0) != 0)
    {
        RecoverOutPipeLocked();
    }
    WdfWaitLockRelease(m_DataPathLock);
}

// IN: the KMDF default sequence for an enabled port (cancel, reset the pipe,
// restart the readers) under the lock. Never resets the port or the device;
// if the reset or start fails the readers stay stopped, logged, until the
// next queue or device restart.
PAGEDX
_Use_decl_annotations_
void
UsbNcmHostDevice::RecoverInPipeLocked(
    void
)
{
    PAGED_CODE();

    const NTSTATUS trigger = InterlockedCompareExchange(&m_RxRecoveryTriggerStatus, 0, 0);
    const USBD_STATUS triggerUsbd = InterlockedCompareExchange(&m_RxRecoveryTriggerUsbdStatus, 0, 0);
    const LONG attempt = InterlockedIncrement(&m_RxRecoveries);

    if (!m_RxPipeRunning || m_DataBulkInPipe == nullptr)
    {
        DbgPrint("Sideline1902: IN recovery #%ld skipped (pipe not running); readers restart "
                 "on the next queue start\n", attempt);
        return;
    }

    if (Apple1902::ClassifyTxCompletion((unsigned)trigger, (unsigned)triggerUsbd) ==
        Apple1902::TxCompletion::DeviceGone)
    {
        DbgPrint("Sideline1902: IN recovery #%ld skipped (device gone, status 0x%08X usbd 0x%08X); "
                 "readers stay stopped\n", attempt, trigger, triggerUsbd);
        m_RxPipeRunning = FALSE;
        SetDataPathFailedLocked();
        return;
    }

    WDFIOTARGET target = WdfUsbTargetPipeGetIoTarget(m_DataBulkInPipe);
    const ULONG64 begin = KeQueryInterruptTime();
    m_RxPipeRunning = FALSE;

    // Also waits for the framework's reader work item to finish.
    WdfIoTargetStop(target, WdfIoTargetCancelSentIo);
    const ULONG64 stopped = KeQueryInterruptTime();

    WDF_REQUEST_SEND_OPTIONS options;
    WDF_REQUEST_SEND_OPTIONS_INIT(&options, WDF_REQUEST_SEND_OPTION_TIMEOUT);
    WDF_REQUEST_SEND_OPTIONS_SET_TIMEOUT(&options, WDF_REL_TIMEOUT_IN_SEC(2));
    const NTSTATUS resetStatus = WdfUsbTargetPipeResetSynchronously(m_DataBulkInPipe, WDF_NO_HANDLE, &options);
    const ULONG64 reset = KeQueryInterruptTime();

    NTSTATUS startStatus = STATUS_SUCCESS;
    ULONG64 started = reset;
    if (NT_SUCCESS(resetStatus))
    {
        // Resubmits the continuous readers.
        startStatus = WdfIoTargetStart(target);
        started = KeQueryInterruptTime();
        m_RxPipeRunning = NT_SUCCESS(startStatus);
    }

    if (!m_RxPipeRunning)
    {
        SetDataPathFailedLocked();
    }
    else
    {
        RestoreDataPathLinkLocked();
    }

    if (!m_RxPipeRunning || ShouldLogOccurrence(attempt))
    {
        DbgPrint("Sideline1902: IN recovery #%ld after status 0x%08X usbd 0x%08X: %s; "
                 "reset 0x%08X start 0x%08X; stop %I64u ms, reset %I64u ms, start %I64u ms\n",
                 attempt, trigger, triggerUsbd,
                 m_RxPipeRunning ? "pipe restarted, data recovery unverified" :
                 "readers stay stopped until queue or device restart (no port or device reset)",
                 resetStatus, startStatus,
                 ElapsedMs(begin, stopped), ElapsedMs(stopped, reset), ElapsedMs(reset, started));
    }
}

// OUT: close admission, drain send sections, cancel sent I/O, reset the pipe,
// then reopen only after a successful start. Never resets or cycles the port
// and never retries a payload. Only the reset request has a time bound (2 s);
// the drain and the cancellation wait depend on the USB stack completing
// cancelled requests, as StopTransmit already does.
PAGEDX
_Use_decl_annotations_
void
UsbNcmHostDevice::RecoverOutPipeLocked(
    void
)
{
    PAGED_CODE();

    const NTSTATUS trigger = InterlockedCompareExchange(&m_TxRecoveryTriggerStatus, 0, 0);
    const USBD_STATUS triggerUsbd = InterlockedCompareExchange(&m_TxRecoveryTriggerUsbdStatus, 0, 0);
    const ULONG64 begin = KeQueryInterruptTime();
    const Apple1902::OutRecoveryPlan plan = Apple1902::TryBeginOutRecovery(
        InterlockedCompareExchange(&m_TxRecoveryEnabled, 0, 0) != 0 &&
            m_TxPipeRunning && m_DataBulkOutPipe != nullptr,
        m_TxRecoveryBudget,
        begin);

    if (plan.Decision == Apple1902::OutRecoveryDecision::Deferred)
    {
        // Preserve the actual XACT_ERROR during cooldown OR token wait:
        // later completions may only time out, without a fresh trigger.
        if (m_TxRecoveryDueTime == 0)
        {
            DbgPrint("Sideline1902: OUT recovery deferred after status 0x%08X usbd 0x%08X; "
                     "remaining %I64u ms, total attempts %I64u\n",
                     trigger, triggerUsbd, (plan.Wait + 9999) / 10000,
                     m_TxRecoveryAttempts);
        }
        m_TxRecoveryDueTime = begin + plan.Wait;
        // Same one shot and lifecycle as cooldown; duplicate callbacks only
        // re-evaluate elapsed credit. No token is spent while deferred.
        WdfTimerStart(m_OutRecoveryTimer, -(LONGLONG)plan.Wait);
        return;
    }

    if (plan.Decision != Apple1902::OutRecoveryDecision::Run)
    {
        // A stopped pipe is terminal for this fault. A lifecycle start may
        // reopen it, but an empty bucket is NEVER a terminal discard.
        const LONG skipped = InterlockedIncrement(&m_TxRecoverySkipped);
        if (ShouldLogOccurrence(skipped))
        {
            DbgPrint("Sideline1902: OUT recovery skipped (pipe not running) #%ld after status "
                     "0x%08X usbd 0x%08X, total attempts %I64u\n",
                     skipped, trigger, triggerUsbd, m_TxRecoveryAttempts);
        }
        m_TxRecoveryDueTime = 0;
        InterlockedExchange(&m_TxRecoveryQueued, 0);
        return;
    }

    const ULONG64 attempt = ++m_TxRecoveryAttempts;
    WDFUSBPIPE pipe = m_DataBulkOutPipe;
    WDFIOTARGET target = WdfUsbTargetPipeGetIoTarget(pipe);
    DbgPrint("Sideline1902: OUT recovery #%I64u start after status 0x%08X usbd 0x%08X\n",
             attempt, trigger, triggerUsbd);

    CloseTxAdmissionLocked();
    m_TxPipeRunning = FALSE;
    m_TxRecoveryDueTime = 0;
    InterlockedExchange64(&m_TxRestartTime, 0);
    const ULONG64 drained = KeQueryInterruptTime();

    // Returns after every sent request's completion routine has run.
    WdfIoTargetStop(target, WdfIoTargetCancelSentIo);
    const ULONG64 stopped = KeQueryInterruptTime();

    WDF_REQUEST_SEND_OPTIONS options;
    WDF_REQUEST_SEND_OPTIONS_INIT(&options, WDF_REQUEST_SEND_OPTION_TIMEOUT);
    WDF_REQUEST_SEND_OPTIONS_SET_TIMEOUT(&options, WDF_REL_TIMEOUT_IN_SEC(2));
    const NTSTATUS resetStatus = WdfUsbTargetPipeResetSynchronously(pipe, WDF_NO_HANDLE, &options);
    const ULONG64 reset = KeQueryInterruptTime();

    NTSTATUS startStatus = STATUS_SUCCESS;
    ULONG64 started = reset;
    if (NT_SUCCESS(resetStatus))
    {
        startStatus = WdfIoTargetStart(target);
        started = KeQueryInterruptTime();
        if (NT_SUCCESS(startStatus))
        {
            m_TxPipeRunning = TRUE;
            // Markers first, then admission: the first send offered after
            // this restart and its first success are logged against it.
            InterlockedExchange(&m_TxPostRestartSuccessLogged, 0);
            InterlockedExchange64(&m_TxPostRestartFirstSend, 0);
            InterlockedExchange64(&m_TxRestartTime, (LONG64)started);
            InterlockedExchange(&m_TxFirstFailureLogged, 0);
            // All pre-reset sends completed during Stop. Consume their
            // fault before reopening; a fast new completion may immediately
            // claim/enqueue a different fault while this callback returns.
            InterlockedExchange(&m_TxRecoveryQueued, 0);
            OpenTxAdmissionLocked();
        }
    }

    // API success is not delivery: data progress is judged only from OUT
    // successes after a send offered after this restart.
    DbgPrint("Sideline1902: OUT recovery #%I64u %s: reset 0x%08X start 0x%08X; "
             "drain %I64u ms, stop %I64u ms, reset %I64u ms, start %I64u ms\n",
             attempt,
             m_TxPipeRunning ? "pipe restarted, data recovery unverified" :
             !NT_SUCCESS(resetStatus) ? "reset failed, OUT closed until queue or device restart" :
             "start failed, OUT closed until queue or device restart",
             resetStatus, startStatus,
             ElapsedMs(begin, drained), ElapsedMs(drained, stopped),
             ElapsedMs(stopped, reset), ElapsedMs(reset, started));

    if (!m_TxPipeRunning)
    {
        InterlockedExchange(&m_TxRecoveryQueued, 0);
        SetDataPathFailedLocked();
    }
    else
    {
        RestoreDataPathLinkLocked();
    }
}

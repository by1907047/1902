// Copyright (C) Microsoft Corporation. All rights reserved.

#include "driver.h"
#include "device.tmh"
#include "apple1902_validation.h"

#define MAX_HOST_NTB_SIZE               (0x10000)
#define MAX_HOST_MTU_SIZE               (9014)
#define MAX_HOST_TX_NTB_DATAGRAM_COUNT  (UINT16) (16)
#define PENDING_BULK_IN_READS           (8)

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
    //  Update the device name with the model from the USB descriptor
    USB_DEVICE_DESCRIPTOR deviceDescriptor;
    PWSTR friendlyName = nullptr;
    WDFMEMORY friendlyNameMemory;
    WDF_OBJECT_ATTRIBUTES objectAttribs;

    WdfUsbTargetDeviceGetDeviceDescriptor(m_WdfUsbTargetDevice, &deviceDescriptor);

    USHORT manufacturerStringLength = 0;
    USHORT productStringLength = 0;

    NCM_RETURN_IF_NOT_NT_SUCCESS_MSG(
        WdfUsbTargetDeviceQueryString(
            m_WdfUsbTargetDevice,
            nullptr,
            nullptr,
            nullptr,
            &manufacturerStringLength,
            deviceDescriptor.iManufacturer,
            0),
        "WdfUsbTargetDeviceQueryString failed");

    NCM_RETURN_IF_NOT_NT_SUCCESS_MSG(
        WdfUsbTargetDeviceQueryString(
            m_WdfUsbTargetDevice,
            nullptr,
            nullptr,
            nullptr,
            &productStringLength,
            deviceDescriptor.iProduct,
            0),
        "WdfUsbTargetDeviceQueryString failed");

    ULONG friendlyNameByteCount = sizeof(WCHAR) * 
        (manufacturerStringLength + 1 +  // 1 white space
         productStringLength + 1);       // allocate 1 more char to make sure string would be null-terminated
   
    WDF_OBJECT_ATTRIBUTES_INIT(&objectAttribs);
    objectAttribs.ParentObject = m_WdfDevice;

    NCM_RETURN_IF_NOT_NT_SUCCESS_MSG(
        WdfMemoryCreate(
            &objectAttribs,
            PagedPool,
            0,
            friendlyNameByteCount,
            &friendlyNameMemory,
            (PVOID *)&friendlyName),
        "WdfMemoryCreate failed");

    RtlZeroMemory(friendlyName, friendlyNameByteCount);

    // The buffer is parented to the long-lived WDFDEVICE; delete it on every
    // path so repeated PrepareHardware does not accumulate copies.
    NTSTATUS status = WdfUsbTargetDeviceQueryString(
        m_WdfUsbTargetDevice,
        nullptr,
        nullptr,
        friendlyName,
        &manufacturerStringLength,
        deviceDescriptor.iManufacturer,
        0);

    if (NT_SUCCESS(status))
    {
        friendlyName[manufacturerStringLength] = L' ';

        status = WdfUsbTargetDeviceQueryString(
            m_WdfUsbTargetDevice,
            nullptr,
            nullptr,
            &friendlyName[manufacturerStringLength + 1],
            &productStringLength,
            deviceDescriptor.iProduct,
            0);
    }

    if (NT_SUCCESS(status))
    {
        WDF_DEVICE_PROPERTY_DATA propertyData;
        WDF_DEVICE_PROPERTY_DATA_INIT(&propertyData, &DEVPKEY_Device_FriendlyName);
        propertyData.Flags = PLUGPLAY_PROPERTY_PERSISTENT;

        status = WdfDeviceAssignProperty(
            m_WdfDevice,
            &propertyData,
            DEVPROP_TYPE_STRING,
            friendlyNameByteCount,
            friendlyName);
    }

    WdfObjectDelete(friendlyNameMemory);

    NCM_RETURN_IF_NOT_NT_SUCCESS_MSG(status, "Friendly name query/assignment failed");

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

    m_HostSelectedNtbInMaxSize = min(
        m_NtbParamters.dwNtbInMaxSize,
        MAX_HOST_NTB_SIZE);

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
    if (hostDevice->m_DataBulkInPipe != nullptr)
    {
        (void) StartPipe(hostDevice->m_DataBulkInPipe);
    }
}

PAGEDX
_Use_decl_annotations_
void
UsbNcmHostDevice::StopReceive(
    WDFDEVICE usbNcmWdfDevice
)
{
    UsbNcmHostDevice* hostDevice = NcmGetHostDeviceFromHandle(usbNcmWdfDevice);
    if (hostDevice->m_DataBulkInPipe != nullptr)
    {
        StopPipe(hostDevice->m_DataBulkInPipe);
    }
}

PAGEDX
_Use_decl_annotations_
void
UsbNcmHostDevice::StartTransmit(
    WDFDEVICE usbNcmWdfDevice
)
{
    UsbNcmHostDevice* hostDevice = NcmGetHostDeviceFromHandle(usbNcmWdfDevice);
    if (hostDevice->m_DataBulkOutPipe != nullptr)
    {
        (void) StartPipe(hostDevice->m_DataBulkOutPipe);
    }
}

PAGEDX
_Use_decl_annotations_
void
UsbNcmHostDevice::StopTransmit(
    WDFDEVICE usbNcmWdfDevice
)
{
    UsbNcmHostDevice* hostDevice = NcmGetHostDeviceFromHandle(usbNcmWdfDevice);
    if (hostDevice->m_DataBulkOutPipe != nullptr)
    {
        StopPipe(hostDevice->m_DataBulkOutPipe);
    }
}

_Use_decl_annotations_
inline
void
UsbNcmHostDevice::TransmitFramesCompetion(
    WDFREQUEST,
    WDFIOTARGET target,
    PWDF_REQUEST_COMPLETION_PARAMS,
    WDFCONTEXT context
)
{
    UsbNcmHostDevice* hostDevice = NcmGetHostDeviceFromHandle(WdfIoTargetGetDevice(target));

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

    // Guard against NULL pipe
    if (hostDevice->m_DataBulkOutPipe == nullptr || hostDevice->m_DataBulkOutPipeMaximumPacketSize == 0)
    {
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

        if (!WdfRequestSend(
                bufferRequest->Request,
                WdfUsbTargetPipeGetIoTarget(hostDevice->m_DataBulkOutPipe), &sendOptions))
        {
            status = WdfRequestGetStatus(bufferRequest->Request);
        }
    }

    return status;
}

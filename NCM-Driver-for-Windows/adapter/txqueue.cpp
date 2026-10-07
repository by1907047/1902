// Copyright (C) Microsoft Corporation. All rights reserved.

#include "adapter.h"
#include "txqueue.tmh"

_Use_decl_annotations_
inline
NcmTxQueue *
NcmTxQueue::Get(
    _In_ NETPACKETQUEUE queue
)
{
    return NcmGetTxQueueFromHandle(queue);
}

PAGEDX
_Use_decl_annotations_
NTSTATUS
NcmTxQueue::EvtCreateTxQueue(
    NETADAPTER netAdapter,
    NETTXQUEUE_INIT * netTxQueueInit
)
{
    NET_PACKET_QUEUE_CONFIG queueConfig;
    WDF_OBJECT_ATTRIBUTES txQueueAttributes;
    NETPACKETQUEUE queue;

    PAGED_CODE();

    NcmAdapter * ncmAdapter = NcmGetAdapterFromHandle(netAdapter);

    NET_PACKET_QUEUE_CONFIG_INIT(
        &queueConfig,
        EvtAdvance,
        EvtSetNotificationEnabled,
        EvtCancel);

    queueConfig.EvtStart = EvtStart;
    queueConfig.EvtStop = EvtStop;

    WDF_OBJECT_ATTRIBUTES_INIT_CONTEXT_TYPE(
        &txQueueAttributes,
        NcmTxQueue);
    txQueueAttributes.EvtCleanupCallback = EvtCleanup;

    NCM_RETURN_IF_NOT_NT_SUCCESS_MSG(
        NetTxQueueCreate(
            netTxQueueInit,
            &txQueueAttributes,
            &queueConfig,
            &queue),
        "NetTxQueueCreate failed");

    // Use the inplacement new and invoke the constructor on the
    // context memory space allocated for queue instance
    NcmTxQueue * txQueue =
        new (NcmGetTxQueueFromHandle(queue)) NcmTxQueue(
            ncmAdapter,
            queue);

    NCM_RETURN_IF_NOT_NT_SUCCESS(txQueue->InitializeQueue());

    return STATUS_SUCCESS;
}

NONPAGEDX
_Use_decl_annotations_
void
NcmTxQueue::EvtCleanup(
    WDFOBJECT object
)
{
    NcmTxQueue * txQueue = NcmGetTxQueueFromHandle(object);
    if (txQueue->m_NcmAdapter != nullptr && txQueue->m_NcmAdapter->m_TxQueue == txQueue)
    {
        txQueue->m_NcmAdapter->m_TxQueue = nullptr;
    }
}

PAGEDX
_Use_decl_annotations_
NTSTATUS
NcmTxQueue::InitializeQueue(
    void
)
{
    NCM_RETURN_IF_NOT_NT_SUCCESS(
        TxBufferRequestPoolCreate(
            m_NcmAdapter->m_WdfDevice,
            m_Queue,
            m_NcmAdapter->m_Parameters.TxMaxNtbSize,
            &m_TxBufferRequestPool));

    NCM_RETURN_IF_NOT_NT_SUCCESS(
        NcmTransferBlockCreate(
            m_Queue,
            m_NcmAdapter->m_Parameters.Use32BitNtb,
            m_NcmAdapter->m_Parameters.TxMaxNtbDatagramCount,
            m_NcmAdapter->m_Parameters.TxNdpAlignment,
            m_NcmAdapter->m_Parameters.TxNdpDivisor,
            m_NcmAdapter->m_Parameters.TxNdpPayloadRemainder,
            &m_NtbHandle));

    m_NcmAdapter->m_TxQueue = this;

    return STATUS_SUCCESS;
}

_Use_decl_annotations_
void
NcmTxQueue::Advance(
    void
)
{
    NcmPacketIterator pi = NcmGetAllPackets(&m_OsQueue);

    while (pi.HasAny())
    {
        if (pi.GetPacket()->Ignore)
        {
            // TX Ignore is read-only: complete without reading or transmitting it.
            pi.Advance();
            pi.Set();
            continue;
        }

        TX_BUFFER_REQUEST * bufferRequest = nullptr;

        NTSTATUS status =
            TxBufferRequestPoolGetBufferRequest(
                m_TxBufferRequestPool,
                &bufferRequest);

        if (NT_SUCCESS(status))
        {
            (void) NcmTransferBlockReInitializeBuffer(
                m_NtbHandle,
                bufferRequest->Buffer,
                bufferRequest->BufferLength,
                NTB_TX);

            bool hasDatagrams = false;
            while (pi.HasAny())
            {
                if (pi.GetPacket()->Ignore)
                {
                    pi.Advance();
                    continue;
                }
                size_t datagramLength = NcmGetPacketDataLength(&pi);
                if (datagramLength < sizeof(ETHERNET_HEADER) ||
                    datagramLength > m_NcmAdapter->m_Parameters.MaxDatagramSize)
                {
                    pi.Advance();
                    continue;
                }

                if (STATUS_SUCCESS != NcmTransferBlockCopyNextDatagram(m_NtbHandle, &pi))
                {
                    if (!hasDatagrams)
                    {
                        // An unfit first packet must not form an empty NTB or stall.
                        pi.Advance();
                        continue;
                    }
                    // Flush a nonempty NTB, then try this packet in a fresh buffer.
                    break;
                }

                hasDatagrams = true;
                // tx is completed instantly once packet is copied
                pi.Advance();
            }

            if (hasDatagrams)
            {
                NcmTransferBlockSetNdp(m_NtbHandle, &bufferRequest->TransferLength);

                status =
                    m_NcmAdapter->m_UsbNcmDeviceCallbacks->EvtUsbNcmTransmitFrames(
                        m_NcmAdapter->GetWdfDevice(),
                        bufferRequest);

                if (!NT_SUCCESS(status))
                {
                    TxBufferRequestPoolReturnBufferRequest(
                        m_TxBufferRequestPool,
                        bufferRequest);
                }
            }
            else
            {
                // All packets were ignored, invalid or too large for this buffer.
                TxBufferRequestPoolReturnBufferRequest(
                    m_TxBufferRequestPool,
                    bufferRequest);
            }
        }
        else
        {
            // no tx buffer available, drop and complete this packet
            pi.Advance();
        }

        pi.Set();
    }
}

PAGEDX
_Use_decl_annotations_
void
NcmTxQueue::Start(
    void
)
{
    PAGED_CODE();
    (void) m_NcmAdapter->m_UsbNcmDeviceCallbacks->EvtUsbNcmStartTransmit(m_NcmAdapter->GetWdfDevice());
}

PAGEDX
_Use_decl_annotations_
void
NcmTxQueue::Stop(
    void
)
{
    PAGED_CODE();
    (void) m_NcmAdapter->m_UsbNcmDeviceCallbacks->EvtUsbNcmStopTransmit(m_NcmAdapter->GetWdfDevice());
}

NONPAGEDX
_Use_decl_annotations_
void
NcmTxQueue::Cancel(
    void
)
{
    // TX payloads are already copied into our own request buffers. Return OS
    // rings without writing the read-only TX Ignore bit (unlike RX cancel).
    NET_RING * packetRing = NetRingCollectionGetPacketRing(m_OsQueue.RingCollection);
    NET_RING * fragmentRing = NetRingCollectionGetFragmentRing(m_OsQueue.RingCollection);
    packetRing->BeginIndex = packetRing->EndIndex;
    fragmentRing->BeginIndex = fragmentRing->EndIndex;
}

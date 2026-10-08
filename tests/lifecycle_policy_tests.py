"""Source-contract checks only; these do not simulate KMDF or prove recovery."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1] / 'NCM-Driver-for-Windows'
SOURCE = (ROOT / 'host/device.cpp').read_text()


def function_body(name):
    start = SOURCE.index('UsbNcmHostDevice::' + name + '(')
    opening = SOURCE.index('{', start)
    depth = 1
    cursor = opening + 1
    while depth:
        depth += (SOURCE[cursor] == '{') - (SOURCE[cursor] == '}')
        cursor += 1
    return SOURCE[opening + 1:cursor - 1]


class LifecyclePolicyTests(unittest.TestCase):
    def test_prepare_reuses_existing_usb_target(self):
        body = function_body('InitializeDevice')
        guard = re.search(r'if\s*\(m_WdfUsbTargetDevice\s*==\s*nullptr\)\s*\{', body)
        self.assertIsNotNone(guard, 'Repeated PrepareHardware must not replace a live USB target')
        create = body.index('status = WdfUsbTargetDeviceCreateWithParameters(')
        opening = body.index('{', guard.start())
        depth, cursor = 1, opening + 1
        while depth:
            depth += (body[cursor] == '{') - (body[cursor] == '}')
            cursor += 1
        self.assertTrue(opening < create < cursor,
                        'USB target creation must be inside the null-handle guard')
        self.assertIn('SelectConfiguration()', body[cursor:])

    def test_negotiated_format_is_recomputed_on_prepare(self):
        body = function_body('SelectConfiguration')
        self.assertRegex(body, r'm_Use32BitNtb\s*=\s*\(m_NtbParamters\.bmNtbFormatsSupported\s*&\s*0x2\)\s*!=\s*0\s*;')

    def test_stop_still_cancels_and_waits(self):
        # Guard the pre-existing quiescence contract; not a dynamic proof.
        self.assertIn('WdfIoTargetStop(wdfIotarget, WdfIoTargetCancelSentIo);', SOURCE)

    def test_reconfigure_invalidates_cached_pipe_handles_before_call(self):
        for name, call in [('SelectConfiguration', 'status = WdfUsbTargetDeviceSelectConfig('),
                           ('SelectSetting', 'status = WdfUsbInterfaceSelectSetting(')]:
            body = function_body(name)
            before = body[:body.index(call)]
            for assignment in ('m_DataBulkInPipe = nullptr;', 'm_DataBulkOutPipe = nullptr;',
                               'm_DataBulkOutPipeMaximumPacketSize = 0;'):
                self.assertIn(assignment, before)

    def test_bulk_in_reader_failures_are_observed(self):
        # The callback must be in the config before the reader is created.
        body = function_body('RetrieveDataBulkPipes')
        assignment = body.index('readerConfig.EvtUsbTargetPipeReadersFailed = '
                                'UsbNcmHostDevice::DataBulkInPipeReadersFailed;')
        self.assertLess(assignment, body.index('WdfUsbTargetPipeConfigContinuousReader('))

    def test_link_speed_precedes_link_up_and_uses_capabilities(self):
        # KMDF's AT_HIGH_SPEED trait is also set at SuperSpeed.
        body = function_body('EnterWorkingState')
        self.assertNotIn('WDF_USB_DEVICE_TRAIT_AT_HIGH_SPEED', body)
        self.assertIn('GUID_USB_CAPABILITY_DEVICE_CONNECTION_SUPER_SPEED_COMPATIBLE', body)
        self.assertIn('GUID_USB_CAPABILITY_DEVICE_CONNECTION_HIGH_SPEED_COMPATIBLE', body)
        self.assertLess(body.index('EvtUsbNcmAdapterSetLinkSpeed('),
                        body.index('EvtUsbNcmAdapterSetLinkState('),
                        'The first link-up indication must carry the queried speed')

    def test_out_recovery_budget_resets_only_per_d0_session(self):
        body = function_body('EnterWorkingState')
        self.assertLess(body.index('BeginD0Session();'), body.index('SelectSetting()'))
        for name in ('StartTransmit', 'StopTransmit', 'RecoverDataPipes', 'RecoverOutPipeLocked'):
            self.assertNotIn('m_TxRecoveryAttempts = 0', function_body(name))
        self.assertIn('m_TxRecoveryAttempts = 0;', function_body('BeginD0Session'))

    def test_stop_transmit_flushes_outside_the_data_path_lock(self):
        body = function_body('StopTransmit')
        recovery = body[body.index('else'):]
        self.assertLess(recovery.index('StopPipe('), recovery.index('WdfWaitLockRelease('))
        self.assertLess(recovery.index('WdfWaitLockRelease('), recovery.index('WdfWorkItemFlush('))

    def test_recovery_timer_drain_and_dispatch_contract(self):
        body = function_body('StopTransmit')
        recovery = body[body.index('else'):]
        order = [recovery.index(s) for s in (
            'WdfWaitLockAcquire(', 'm_TxRecoveryEnabled, 0)',
            'CloseTxAdmissionLocked();', 'StopPipe(', 'WdfTimerStop(',
            'm_TxRecoveryQueued, 0)', 'WdfWaitLockRelease(', 'WdfWorkItemFlush(')]
        self.assertEqual(order, sorted(order))
        timer = function_body('OutRecoveryTimer')
        for call in ('WdfWaitLockAcquire', 'WdfIoTargetStop', 'WdfIoTargetStart',
                     'WdfUsbTargetPipeResetSynchronously', 'WdfWorkItemFlush', 'WdfTimerStop'):
            self.assertNotIn(call, timer)
        self.assertIn('m_TxRecoveryEnabled', timer)
        self.assertIn('m_TxRecoveryQueued', timer)
        self.assertIn('WdfWorkItemEnqueue', timer)
        create = function_body('InitializeDataPathControl')
        self.assertIn('WDF_TIMER_CONFIG_INIT(&config, UsbNcmHostDevice::OutRecoveryTimer)', create)
        self.assertIn('attributes.ExecutionLevel = WdfExecutionLevelDispatch;', create)
        self.assertLess(create.rindex('config.AutomaticSerialization = FALSE;'),
                        create.index('WdfTimerCreate('))

    def test_success_never_consumes_pending_fault_and_reopen_does(self):
        self.assertNotIn('m_TxRecoveryQueued', function_body('TransmitFramesCompetion'))
        out = function_body('RecoverOutPipeLocked')
        reopen = out.index('OpenTxAdmissionLocked();')
        preceding = out[:reopen]
        self.assertGreater(preceding.rindex('m_TxRecoveryQueued, 0)'),
                           preceding.index('WdfIoTargetStart('))
        self.assertIn('if (!m_TxPipeRunning)', out[reopen:])

    def test_recovery_never_escalates_and_keeps_order(self):
        for call in ('ResetPortSynchronously', 'CyclePortSynchronously', 'WdfUsbTargetDeviceReset'):
            self.assertNotIn(call, SOURCE)
        out = function_body('RecoverOutPipeLocked')
        order = [out.index(s) for s in ('CloseTxAdmissionLocked();', 'WdfIoTargetStop(',
                                        'WdfUsbTargetPipeResetSynchronously(',
                                        'WdfIoTargetStart(', 'OpenTxAdmissionLocked();')]
        self.assertEqual(order, sorted(order))
        rx = function_body('RecoverInPipeLocked')
        order = [rx.index(s) for s in ('WdfIoTargetStop(', 'WdfUsbTargetPipeResetSynchronously(',
                                       'WdfIoTargetStart(')]
        self.assertEqual(order, sorted(order))
        for body in (out, rx):
            self.assertIn('WDF_REL_TIMEOUT_IN_SEC(2)', body)
            self.assertNotIn('"recovered', body)

    def test_readers_failed_callback_never_blocks_or_stops(self):
        # Stopping a reader pipe waits for the work item running this callback.
        body = function_body('DataBulkInPipeReadersFailed')
        for call in ('WdfWaitLockAcquire', 'WdfIoTargetStop', 'WdfIoTargetStart',
                     'WdfUsbTargetPipeResetSynchronously', 'WdfWorkItemFlush'):
            self.assertNotIn(call, body)
        self.assertLess(body.index('return TRUE;'), body.index('RequestInPipeRecovery('))
        self.assertIn('return FALSE;', body)

    def test_device_add_reads_the_switch(self):
        driver = (ROOT / 'host/driver.cpp').read_text()
        self.assertIn('hostDevice->InitializeDataPathControl();', driver)

if __name__ == '__main__':
    unittest.main()

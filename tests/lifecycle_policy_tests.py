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

    def test_link_speed_precedes_link_up_and_uses_capabilities(self):
        # KMDF's AT_HIGH_SPEED trait is also set at SuperSpeed.
        body = function_body('EnterWorkingState')
        self.assertNotIn('WDF_USB_DEVICE_TRAIT_AT_HIGH_SPEED', body)
        self.assertIn('GUID_USB_CAPABILITY_DEVICE_CONNECTION_SUPER_SPEED_COMPATIBLE', body)
        self.assertIn('GUID_USB_CAPABILITY_DEVICE_CONNECTION_HIGH_SPEED_COMPATIBLE', body)
        self.assertLess(body.index('EvtUsbNcmAdapterSetLinkSpeed('),
                        body.index('EvtUsbNcmAdapterSetLinkState('),
                        'The first link-up indication must carry the queried speed')


if __name__ == '__main__':
    unittest.main()

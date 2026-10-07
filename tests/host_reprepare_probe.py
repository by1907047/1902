"""Execute production host creation prefix and SelectSetting with OS shims.

This verifies local control-flow/failure cleanup only, not KMDF scheduling,
USB I/O cancellation, actual sleep/hot-plug recovery, or a loadable SYS build.
"""
from pathlib import Path
import subprocess
import tempfile
from lifecycle_policy_tests import function_body

# Deliberately stop before USB descriptor/adapter calls: no pretend USB bus.
creation_prefix = function_body('InitializeDevice').split(
    '// Independent experiment: only the 1902 composite parent is supported.')[0]
setting_body = function_body('SelectSetting')
shim = r'''
#include <cassert>
#include <cstdio>
#define PAGED_CODE() ((void)0)
#define NT_SUCCESS(s) ((s)>=0)
#define DbgPrint(...) ((void)0)
using NTSTATUS=int;
using WDFUSBDEVICE=void*;
using WDFDEVICE=void*;
using WDFUSBPIPE=void*;
constexpr int STATUS_SUCCESS=0,STATUS_FAILURE=-1;
constexpr auto WDF_NO_OBJECT_ATTRIBUTES=nullptr;
constexpr int USBD_CLIENT_CONTRACT_VERSION_602=602;
constexpr int USB_REQUEST_SET_NTB_FORMAT=1,USB_REQUEST_SET_NTB_INPUT_SIZE=2;
constexpr int BmRequestHostToDevice=0,BmRequestToInterface=1;
using PVOID=void*;
struct WDF_USB_DEVICE_INFORMATION {};
struct WDF_USB_DEVICE_CREATE_CONFIG {int contract;};
struct WDF_USB_INTERFACE_SELECT_SETTING_PARAMS {int setting;};
struct WDF_MEMORY_DESCRIPTOR {void* buffer;size_t size;};
#define WDF_USB_DEVICE_CREATE_CONFIG_INIT(p,c) ((p)->contract=(c))
#define WDF_USB_INTERFACE_SELECT_SETTING_PARAMS_INIT_SETTING(p,s) ((p)->setting=(s))
#define WDF_MEMORY_DESCRIPTOR_INIT_BUFFER(p,b,s) ((p)->buffer=(b),(p)->size=(s))
static int createCalls=0,createFailCount=0,configureCalls=0,failStep=0;
static NTSTATUS WdfUsbTargetDeviceCreateWithParameters(WDFDEVICE,
 WDF_USB_DEVICE_CREATE_CONFIG* c,void*,WDFUSBDEVICE* out){
 assert(c->contract==602);++createCalls;
 if(createFailCount>0){--createFailCount;return STATUS_FAILURE;}
 *out=reinterpret_cast<void*>(42);return STATUS_SUCCESS;
}
static NTSTATUS NextConfig(){++configureCalls;return configureCalls==failStep?STATUS_FAILURE:STATUS_SUCCESS;}
static NTSTATUS WdfUsbInterfaceSelectSetting(void*,void*,WDF_USB_INTERFACE_SELECT_SETTING_PARAMS*){return NextConfig();}
struct UsbNcmHostDevice {
 WDFDEVICE m_WdfDevice=nullptr;WDFUSBDEVICE m_WdfUsbTargetDevice=nullptr;
 void* m_DataInterface=nullptr;
 WDFUSBPIPE m_DataBulkInPipe=reinterpret_cast<void*>(1);
 WDFUSBPIPE m_DataBulkOutPipe=reinterpret_cast<void*>(2);
 unsigned m_DataBulkOutPipeMaximumPacketSize=1024;
 bool m_Use32BitNtb=true;
 struct {unsigned dwNtbInMaxSize=128;} m_NtbParamters;
 unsigned m_HostSelectedNtbInMaxSize=64;
 NTSTATUS CreationPrefix();NTSTATUS SelectSetting();
 NTSTATUS RequestClassSpecificControlTransfer(int,int,int,int,WDF_MEMORY_DESCRIPTOR*){return NextConfig();}
};
'''
functions = ('NTSTATUS UsbNcmHostDevice::CreationPrefix(){' + creation_prefix +
             '\nreturn STATUS_SUCCESS;\n}\n' +
             'NTSTATUS UsbNcmHostDevice::SelectSetting(){' + setting_body + '\n}\n')
main = r'''
int main(){
 int checks=0;
 UsbNcmHostDevice host;
 for(int i=0;i<200;++i){assert(host.CreationPrefix()==STATUS_SUCCESS);++checks;}
 assert(createCalls==1&&host.m_WdfUsbTargetDevice==reinterpret_cast<void*>(42));++checks;
 std::puts("200 repeated preparation prefixes preserve one USB target PASS");
 UsbNcmHostDevice retry;createFailCount=1;
 assert(retry.CreationPrefix()==STATUS_FAILURE&&!retry.m_WdfUsbTargetDevice);++checks;
 assert(retry.CreationPrefix()==STATUS_SUCCESS&&retry.m_WdfUsbTargetDevice);++checks;
 assert(createCalls==3);++checks;
 std::puts("creation failure retains null and retries without replacing live target PASS");
 for(int stage=1;stage<=4;++stage){
  UsbNcmHostDevice device;failStep=stage;configureCalls=0;
  assert(device.SelectSetting()==STATUS_FAILURE);++checks;
  assert(!device.m_DataBulkInPipe&&!device.m_DataBulkOutPipe&&
         !device.m_DataBulkOutPipeMaximumPacketSize);++checks;
  assert(configureCalls==stage);++checks;
 }
 UsbNcmHostDevice success;failStep=0;configureCalls=0;
 assert(success.SelectSetting()==STATUS_SUCCESS&&configureCalls==4);++checks;
 assert(!success.m_DataBulkInPipe&&!success.m_DataBulkOutPipe&&
        !success.m_DataBulkOutPipeMaximumPacketSize);++checks;
 std::puts("all four alternate-setting/control-transfer failure points leave no cached data pipes PASS");
 std::printf("host reprepare control-flow: %d checks, 0 failures\n",checks);
}
'''

if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='sideline-ncm-reprepare-') as tmp:
        binary = Path(tmp)/'probe'
        subprocess.run(['clang++','-std=c++17','-fsanitize=address,undefined',
                        '-g','-x','c++','-','-o',str(binary)],
                       input=shim+functions+main,text=True,check=True)
        subprocess.run([str(binary)],check=True)

"""Run production SetDeviceFriendlyName/SelectConfiguration with WDF shims.

Injects a failure at every fallible WDF/USB call in turn and checks that no
WDFMEMORY created by either function is still alive on return. The naming path
must assign a stable, terminated adapter name without querying USB strings or
allocating memory. Does not simulate KMDF object trees, IRQL or real USB I/O.
"""
from pathlib import Path
import subprocess
import sys
import tempfile
from lifecycle_policy_tests import ROOT, function_body

header = (ROOT/'inc/ncm.h').read_text()
ntb_parameters = header[header.index('typedef struct _NTB_PARAMETERS'):
                        header.index('} NTB_PARAMETERS, *PNTB_PARAMETERS;')] + '} NTB_PARAMETERS;\n'
validation = (ROOT.parent/'tests/validation_tests.cpp').read_text()
fixture = validation[validation.index('static std::vector<unsigned char> Fixture()'):
                     validation.index('int main()')]

shim = r'''
#include <cassert>
#include <cstdio>
#include <cstring>
#include <cstdint>
#include <cwchar>
#include <set>
#include <string>
#include <vector>
#include "host/apple1902_validation.h"
#define PAGED_CODE() ((void)0)
#define NT_SUCCESS(s) ((s)>=0)
#define DbgPrint(...) ((void)0)
#define NCM_RETURN_IF_NOT_NT_SUCCESS_MSG(e,m) do{NTSTATUS s_=(e);if(!NT_SUCCESS(s_))return s_;}while(0)
#define NCM_RETURN_NT_STATUS_IF_FALSE_MSG(c,s,m) do{if(!(c))return (s);}while(0)
#define RtlZeroMemory(d,n) std::memset((d),0,(n))
#define ARRAYSIZE(a) (sizeof(a)/sizeof((a)[0]))
#define min(a,b) ((a)<(b)?(a):(b))
#define MAX_HOST_MTU_SIZE (9014)
using NTSTATUS=int;using ULONG=unsigned;using PULONG=ULONG*;using USHORT=unsigned short;
using BYTE=unsigned char;using UCHAR=unsigned char;using BOOLEAN=bool;using PVOID=void*;
using UINT8=uint8_t;using UINT16=uint16_t;using UINT32=uint32_t;
using WCHAR=wchar_t;using PWSTR=wchar_t*;
using WDFDEVICE=void*;using WDFUSBDEVICE=void*;using WDFUSBINTERFACE=void*;using WDFUSBPIPE=void*;
constexpr int STATUS_SUCCESS=0,STATUS_UNSUCCESSFUL=-1,STATUS_BUFFER_TOO_SMALL=-2,
 STATUS_DEVICE_CONFIGURATION_ERROR=-3,STATUS_DEVICE_HARDWARE_ERROR=-4;
constexpr int NonPagedPoolNx=0,PagedPool=1,PLUGPLAY_PROPERTY_PERSISTENT=1,DEVPROP_TYPE_STRING=18;
constexpr int USB_REQUEST_GET_NTB_PARAMETERS=0x80,BmRequestDeviceToHost=1,BmRequestToInterface=1;
constexpr void* WDF_NO_OBJECT_ATTRIBUTES=nullptr;
static const int DEVPKEY_Device_FriendlyName=0;
#pragma pack(push,1)
''' + ntb_parameters + r'''
#pragma pack(pop)
static_assert(sizeof(NTB_PARAMETERS)==28,"NTB_PARAMETERS layout");
struct Memory{std::vector<unsigned char> bytes;};
using WDFMEMORY=Memory*;
static std::set<Memory*> live;
static int calls=0,failAt=0;
static bool Fail(){return ++calls==failAt;}
static unsigned advertisedFormats=3,advertisedInMax=0x10000,advertisedOutMax=0x10000;
struct WDF_OBJECT_ATTRIBUTES{void* ParentObject;};
#define WDF_OBJECT_ATTRIBUTES_INIT(a) ((a)->ParentObject=nullptr)
static NTSTATUS WdfMemoryCreate(WDF_OBJECT_ATTRIBUTES* a,int,int,size_t size,WDFMEMORY* out,PVOID* buffer){
 assert(a&&a->ParentObject);
 if(Fail())return STATUS_UNSUCCESSFUL;
 auto* m=new Memory;m->bytes.resize(size,0xcc);live.insert(m);*out=m;
 if(buffer)*buffer=m->bytes.data();return STATUS_SUCCESS;
}
static void WdfObjectDelete(WDFMEMORY m){assert(live.erase(m)==1);delete m;}
struct USB_DEVICE_DESCRIPTOR{UCHAR iManufacturer,iProduct;};
static void WdfUsbTargetDeviceGetDeviceDescriptor(WDFUSBDEVICE,USB_DEVICE_DESCRIPTOR* d){d->iManufacturer=1;d->iProduct=2;}
static const wchar_t* StringFor(UCHAR index){
 switch(index){case 1:return L"Apple Inc.";case 2:return L"Mac";case 4:return L"02aB3456789c";}
 assert(false);return L"";
}
static NTSTATUS WdfUsbTargetDeviceQueryString(WDFUSBDEVICE,void*,void*,PWSTR text,USHORT* count,UCHAR index,USHORT){
 if(Fail())return STATUS_UNSUCCESSFUL;
 const wchar_t* value=StringFor(index);const USHORT length=(USHORT)std::wcslen(value);
 if(text){assert(*count>=length);std::wmemcpy(text,value,length);}
 *count=length;return STATUS_SUCCESS;
}
struct WDF_DEVICE_PROPERTY_DATA{const void* PropertyKey;ULONG Flags;};
#define WDF_DEVICE_PROPERTY_DATA_INIT(d,k) ((d)->PropertyKey=(k),(d)->Flags=0)
static std::wstring assigned;
static NTSTATUS WdfDeviceAssignProperty(WDFDEVICE,WDF_DEVICE_PROPERTY_DATA* d,int type,ULONG size,PVOID data){
 assert(d->PropertyKey==&DEVPKEY_Device_FriendlyName&&type==DEVPROP_TYPE_STRING);
 if(Fail())return STATUS_UNSUCCESSFUL;
 const auto* text=static_cast<const wchar_t*>(data);
 assert(size%sizeof(WCHAR)==0&&text[size/sizeof(WCHAR)-1]==0);
 assigned=text;return STATUS_SUCCESS;
}
''' + fixture + r'''
struct USB_CONFIGURATION_DESCRIPTOR{UCHAR bLength;};
using PUSB_CONFIGURATION_DESCRIPTOR=USB_CONFIGURATION_DESCRIPTOR*;
static NTSTATUS WdfUsbTargetDeviceRetrieveConfigDescriptor(WDFUSBDEVICE,PVOID buffer,USHORT* size){
 if(Fail())return STATUS_UNSUCCESSFUL;
 const auto bytes=Fixture();
 if(!buffer){*size=(USHORT)bytes.size();return STATUS_BUFFER_TOO_SMALL;}
 assert(*size>=bytes.size());std::memcpy(buffer,bytes.data(),bytes.size());*size=(USHORT)bytes.size();
 return STATUS_SUCCESS;
}
static BYTE WdfUsbInterfaceGetNumSettings(WDFUSBINTERFACE){return 2;}
static BYTE WdfUsbTargetDeviceGetNumInterfaces(WDFUSBDEVICE){return 4;}
static WDFUSBINTERFACE WdfUsbTargetDeviceGetInterface(WDFUSBDEVICE,BYTE i){return reinterpret_cast<void*>(uintptr_t(100+i));}
static BYTE WdfUsbInterfaceGetInterfaceNumber(WDFUSBINTERFACE i){return BYTE(reinterpret_cast<uintptr_t>(i)-100);}
struct WDF_USB_INTERFACE_SETTING_PAIR{WDFUSBINTERFACE UsbInterface;UCHAR SettingIndex;};
struct WDF_USB_DEVICE_SELECT_CONFIG_PARAMS{ULONG count;WDF_USB_INTERFACE_SETTING_PAIR* pairs;};
#define WDF_USB_DEVICE_SELECT_CONFIG_PARAMS_INIT_MULTIPLE_INTERFACES(p,n,s) ((p)->count=(n),(p)->pairs=(s))
static NTSTATUS WdfUsbTargetDeviceSelectConfig(WDFUSBDEVICE,void*,WDF_USB_DEVICE_SELECT_CONFIG_PARAMS* p){
 assert(p->count==4);for(ULONG i=0;i<4;++i)assert(p->pairs[i].UsbInterface);
 return Fail()?STATUS_UNSUCCESSFUL:STATUS_SUCCESS;
}
struct WDF_MEMORY_DESCRIPTOR{PVOID buffer;size_t size;};
#define WDF_MEMORY_DESCRIPTOR_INIT_BUFFER(d,b,s) ((d)->buffer=(b),(d)->size=(s))
struct UsbNcmHostDevice{
 WDFDEVICE m_WdfDevice=reinterpret_cast<void*>(1);
 WDFUSBDEVICE m_WdfUsbTargetDevice=reinterpret_cast<void*>(2);
 WDFUSBINTERFACE m_ControlInterface=reinterpret_cast<void*>(100);
 WDFUSBINTERFACE m_DataInterface=reinterpret_cast<void*>(101);
 WDFUSBPIPE m_DataBulkInPipe=nullptr,m_DataBulkOutPipe=nullptr;
 ULONG m_DataBulkOutPipeMaximumPacketSize=0;
 BYTE m_MacAddress[6]={};NTB_PARAMETERS m_NtbParamters={};BOOLEAN m_Use32BitNtb=false;
 UINT16 m_MaxDatagramSize=0;UINT32 m_HostSelectedNtbInMaxSize=0;
 NTSTATUS SetDeviceFriendlyName();NTSTATUS SelectConfiguration();
 NTSTATUS RequestClassSpecificControlTransfer(UINT8 request,int,int,UINT16,WDF_MEMORY_DESCRIPTOR* d,PULONG transferred=nullptr){
  assert(request==USB_REQUEST_GET_NTB_PARAMETERS&&d->size==28);
  if(Fail())return STATUS_UNSUCCESSFUL;
  unsigned char ntb[28]={28,0,3,0,0,0,1,0,4,0,0,0,4,0,0,0,0,0,1,0,4,0,0,0,4,0,16,0};
  ntb[2]=(unsigned char)advertisedFormats;
  for(int i=0;i<4;++i){ntb[4+i]=(unsigned char)(advertisedInMax>>(8*i));ntb[16+i]=(unsigned char)(advertisedOutMax>>(8*i));}
  std::memcpy(d->buffer,ntb,28);if(transferred)*transferred=28;return STATUS_SUCCESS;
 }
};
'''
functions = ''.join(
    f'NTSTATUS UsbNcmHostDevice::{name}(){{{function_body(name)}\n}}\n'
    for name in ('SetDeviceFriendlyName', 'SelectConfiguration'))
main = r'''
template<class Run,class Success>
static int Sweep(const char* name,Run run,Success success){
 int checks=0;
 for(failAt=1;;++failAt){
  calls=0;UsbNcmHostDevice host;assigned.clear();
  const NTSTATUS status=run(host);
  const bool injected=failAt<=calls;
  if(!live.empty())std::printf("%s: %zu WDFMEMORY live after failure point %d\n",name,live.size(),failAt);
  assert(live.empty());++checks;
  if(!injected){assert(status==STATUS_SUCCESS);success(host);++checks;break;}
  assert(!NT_SUCCESS(status));++checks;
 }
 std::printf("%s: %d fallible calls, no WDFMEMORY retained on any path PASS\n",name,failAt-1);
 return checks;
}
int main(){
 int checks=0;
 checks+=Sweep("SetDeviceFriendlyName",[](UsbNcmHostDevice& h){return h.SetDeviceFriendlyName();},
  [](UsbNcmHostDevice&){assert(assigned==L"Apple USB NCM Network Adapter"&&calls==1);});
 checks+=Sweep("SelectConfiguration",[](UsbNcmHostDevice& h){return h.SelectConfiguration();},
  [](UsbNcmHostDevice& h){
   assert(h.m_MaxDatagramSize==1514&&h.m_Use32BitNtb&&h.m_HostSelectedNtbInMaxSize==0x10000);
   assert(h.m_MacAddress[0]==2&&h.m_MacAddress[1]==0xab&&h.m_MacAddress[5]==0x9c);
  });
 // Larger advertised IN sizes are negotiated down rather than rejected.
 struct Case{unsigned formats,inMax,outMax,selected;bool ntb32;};
 for(Case c : {Case{3,0x20000,0x10000,0x10000,true},Case{1,0x20000,0xffff,0xffff,false},
               Case{1,0x4000,0xffff,0x4000,false}}){
  advertisedFormats=c.formats;advertisedInMax=c.inMax;advertisedOutMax=c.outMax;
  failAt=0;calls=0;UsbNcmHostDevice host;
  assert(host.SelectConfiguration()==STATUS_SUCCESS&&live.empty());
  assert(host.m_HostSelectedNtbInMaxSize==c.selected&&host.m_Use32BitNtb==c.ntb32);++checks;
 }
 std::puts("advertised IN 0x20000 selects host limit for NTB32/NTB16 PASS");
 std::printf("host per-prepare memory: %d checks, 0 failures\n",checks);
}
'''


def run_probe():
    with tempfile.TemporaryDirectory(prefix='sideline-ncm-memory-') as tmp:
        cpp = Path(tmp)/'probe.cpp'
        cpp.write_text(shim+functions+main)
        binary = Path(tmp)/'probe'
        subprocess.run(['clang++','-std=c++17','-fsanitize=address,undefined','-g',
                        '-I',str(ROOT),str(cpp),'-o',str(binary)],check=True)
        return subprocess.run([str(binary)]).returncode


if __name__ == '__main__':
    sys.exit(run_probe())

"""Exercise reserved-zero NTB construction using the production template.

Portable ASan/UBSan fixture only; does not load a driver or access devices.
Dirty backing buffers and large-to-small reuse prevent implicit zero-fill
from hiding uninitialized NDP32 reserved fields.
"""
from pathlib import Path
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ntb_review_probe import shim, structures, template

main = r'''
using Test16=NcmTransferBlock<NcmTransferHeader16,NcmDatagramPointerTable16,NcmDatagramPointer16,
                            UINT16,0x484d434e,0x304d434e,0x314d434e>;
using Test32=NcmTransferBlock<NcmTransferHeader32,NcmDatagramPointerTable32,NcmDatagramPointer32,
                            UINT32,0x686d636e,0x306d636e,0x316d636e>;
static unsigned checks=0;
template<class Ntb,class Nth,class Ndp,class Dpe>
static void Build(Ntb& ntb,std::vector<uint8_t>& buffer,const std::vector<size_t>& sizes) {
  assert(ntb.ReInitializeBuffer(buffer.data(),buffer.size(),NTB_TX)==STATUS_SUCCESS);
  NcmPacketIterator packet;
  for(size_t bytes:sizes) {
    packet.packet.assign(bytes,0x3c);
    assert(ntb.CopyNextDatagram(&packet)==STATUS_SUCCESS);
  }
  auto beforeHeader=buffer;
  size_t length=0; ntb.SetNdp(&length);
  auto *nth=reinterpret_cast<Nth*>(buffer.data());
  auto *ndp=reinterpret_cast<Ndp*>(buffer.data()+nth->NdpIndex);
  assert(ndp->NextNdpIndex==0);
  assert(ndp->Length==sizeof(Ndp)+(sizes.size()+1)*sizeof(Dpe));
  assert(length==nth->NdpIndex+ndp->Length);
  if constexpr(sizeof(Ndp)==16) {
    if(ndp->Reserved6!=0 || ndp->Reserved12!=0) {
      std::fprintf(stderr,"FAIL: reserved6=%04x reserved12=%08x NDP@%u bytes=%zu\n",
                   ndp->Reserved6,ndp->Reserved12,unsigned(nth->NdpIndex),length);
      std::abort();
    }
  }
  auto *dpe=reinterpret_cast<Dpe*>(buffer.data()+nth->NdpIndex+sizeof(Ndp));
  for(size_t i=0;i<sizes.size();++i) {
    assert(dpe[i].DatagramLength==sizes[i]);
    for(size_t j=0;j<sizes[i];++j) assert(buffer[dpe[i].DatagramIndex+j]==0x3c);
  }
  assert(dpe[sizes.size()].DatagramIndex==0 && dpe[sizes.size()].DatagramLength==0);
  for(size_t j=length;j<buffer.size();++j) assert(buffer[j]==beforeHeader[j]);
  ++checks;
}
template<class Ntb,class Nth,class Ndp,class Dpe>
static void Matrix(bool use32) {
  for(size_t alignment:{size_t(4),size_t(8),size_t(16),size_t(32)}) {
    Ntb ntb;
    assert(ntb.InitializeNtb(nullptr,16,alignment,4,0,use32)==STATUS_SUCCESS);
    for(uint8_t fill:{uint8_t(0),uint8_t(0xa5),uint8_t(0x5a)}) {
      std::vector<uint8_t> buffer(32768,fill);
      for(size_t bytes:{size_t(14),size_t(64),size_t(1000),size_t(1514),size_t(4096),size_t(8192),size_t(32000)})
        Build<Ntb,Nth,Ndp,Dpe>(ntb,buffer,{bytes});
      Build<Ntb,Nth,Ndp,Dpe>(ntb,buffer,{4096,64,1514});
      Build<Ntb,Nth,Ndp,Dpe>(ntb,buffer,{64});
    }
  }
}
int main() {
  Matrix<Test16,NcmTransferHeader16,NcmDatagramPointerTable16,NcmDatagramPointer16>(false);
  std::printf("NTB16 dirty/reused/alignment controls: %u passed\n",checks);
  Matrix<Test32,NcmTransferHeader32,NcmDatagramPointerTable32,NcmDatagramPointer32>(true);
  std::printf("PASS: %u NTB16/32 reserved-zero, payload, DPE and tail-preservation cases\n",checks);
}
'''

with tempfile.TemporaryDirectory(prefix='sideline-ncm-reserved-regression-') as temporary:
    source = Path(temporary) / 'regression.cpp'
    source.write_text(shim + '\n#include <cstdlib>\n#pragma pack(push,1)\n' + structures + '\n#pragma pack(pop)\n' + template + main)
    binary = Path(temporary) / 'regression'
    subprocess.run(['clang++', '-std=c++17', '-fsanitize=address,undefined',
                    '-g', str(source), '-o', str(binary)], check=True)
    result = subprocess.run([str(binary)])
    sys.exit(result.returncode if result.returncode >= 0 else 128 - result.returncode)

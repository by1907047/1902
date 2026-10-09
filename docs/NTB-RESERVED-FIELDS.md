# NDP reserved-field initialization

The NDP32 header contains reserved fields of two bytes at offset 6 and four
bytes at offset 12. USB-IF NCM 1.0 Errata 1, section 3.3.2/Table 3-4 requires both
to be zero. See the [official specification archive](https://www.usb.org/sites/default/files/NCM10_012011.zip).

The previous `SetNdp` wrote the signature, length and next-table index but
left those six bytes untouched. A later smaller NTB can place its header in
the old Ethernet payload of a reused TX buffer. Starting from a zero-backed
buffer, a 4096-byte datagram followed by a 64-byte datagram reproduced nonzero
reserved fields. This is a protocol-conformance defect, not a demonstrated
cause of the intermittent USB OUT transaction error.

The correction clears only `sizeof(NDP)` before assigning its named fields:
8 bytes for NDP16 or 16 for NDP32. It does not clear the full buffer, change
wire lengths, replay payloads or alter recovery, timeout or power policy.

`python3 tests/ntb_reserved_fields_probe.py` compiles the actual production
template under ASan/UBSan. Its 216 cases cover dirty backing buffers,
large-to-small reuse, multiple datagrams, four NDP alignments, mandatory DPE
terminators, payload bytes and unchanged tail bytes. The old NTB32 code fails
the reserved-zero assertion; the header-only correction passes. Native build
and hardware results must be recorded separately for the exact new commit.

Current hardware traces confirm successful `SET_NTB_FORMAT=1` (NTB32).
Headers-only ETW does not show the reserved bytes in the failing transfer,
so format relevance alone must not be reported as fault causality. Keep
this correctness change separate from the preceding deferred-recovery
revision when comparing results. A finite clean trial is not proof that
the initiating transaction error has been eliminated.

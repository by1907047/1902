# Device and project naming

The project uses consistent Windows display names without development-status
suffixes. Naming does not imply Microsoft signing, WHQL certification, or Apple
endorsement. Signing and compatibility remain documented separately.

| Surface | Name |
| --- | --- |
| GitHub repository | `apple-usb-ncm` |
| Project title | Apple USB NCM Driver for Windows |
| Device Manager / network adapter description | Apple USB NCM Network Adapter |
| Driver service display name | Apple USB NCM Driver |
| Driver provider | Sideline |
| Package label | Apple USB NCM Driver Package |
| Maintainer's Windows connection alias | Mac USB Network |

The connection alias is local, editable Windows configuration. The driver does
not impose it on every installation or overwrite a user's chosen alias.

The runtime PnP friendly name and INF device description use the same adapter
name. The friendly name is assigned from the driver's constant string, including
its terminating null, rather than optional Mac manufacturer/product strings.
This avoids the blank-space name observed when both firmware strings were empty.
No USB request or retained allocation is needed for display naming.

Internal identifiers remain unchanged for upgrade compatibility: service/SYS
`SidelineAppleNcm1902`, hardware ID `USB\VID_05AC&PID_1902`, and existing diagnostic
registry names. Display-name changes do not alter power, routing or data-path
behavior. The frozen alpha.2 artifacts retain their original names and hashes;
renamed packages require a new build, signature and validation.

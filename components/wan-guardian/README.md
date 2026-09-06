# WAN Guardian

The source in `scripts/` is imported unchanged from the working router snapshot.

`wan-guardian.sh` performs staged diagnosis and recovery for the current device's `ISP` / `eth3` WAN path. `wan-recovery-actuator.sh` performs the narrow DHCP client renewal action.

These identifiers are device-specific and must be parameterized or detected before the component is considered portable.

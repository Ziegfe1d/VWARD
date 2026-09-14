# AdGuard Home ownership contract

`VWARD Ads & Privacy Guard` is an auxiliary intelligence/automation layer. AdGuard Home remains the native DNS filtering engine.

## VWARD may

- read ordinary allowed query history;
- build its own generated rules;
- read AGH filtering status/user rules through the official local API;
- publish only the VWARD-owned marker block when `PUBLISH_MODE=user_rules_api` is explicitly enabled;
- later replace/remove rules that were created inside that VWARD marker block.

## VWARD must not

- edit or remove built-in/remote AGH subscriptions;
- delete unrelated manual AGH user rules;
- infer ownership from rule text alone outside the VWARD marker block;
- rewrite `AdGuardHome.yaml` directly in candidate v5;
- restart AdGuard Home merely to publish VWARD rules;
- auto-unblock a previous VWARD block solely because a remote source stopped listing it.

## Marker boundary

```text
! VWARD ADS & PRIVACY GUARD BEGIN
...owned rules...
! VWARD ADS & PRIVACY GUARD END
```

`filtering/set_rules` replaces the complete AGH user-rules array. Therefore the publisher first reads the current array, strips only an existing VWARD marker block, preserves every remaining entry, appends the new VWARD block, and rechecks that the live array is unchanged before writing. A concurrent change aborts the operation before mutation. The publisher then reads the result back; write/verification failure restores the saved previous array, and rollback succeeds only after exact read-back verification.

## Rule precedence inside VWARD

1. manual VWARD ALLOW/BLOCK;
2. explicit never-auto-block / trust policy;
3. valid cached VWARD verdict;
4. ACTIVE external evidence;
5. CHECK external evidence for explanation/review only;
6. heuristics for SUSPECT/review only.

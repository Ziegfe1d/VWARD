package plan

import "testing"

// Keenetic 5.1.8 refuses «dns-proxy no route object-group G T auto» over RCI and keeps the
// route (Viva 12.11.2026, the tunnel switch left every list on the dead tunnel): a removal
// carries no options, an addition keeps them.
func TestRouteRemovalWithoutOptions(t *testing.T) {
	if got := routeCmd("no ", "domain-list0", "OpkgTun4", "auto"); got != "dns-proxy no route object-group domain-list0 OpkgTun4" {
		t.Fatalf("removal: %q", got)
	}
	if got := routeCmd("", "domain-list0", "OpkgTun0", "auto"); got != "dns-proxy route object-group domain-list0 OpkgTun0 auto" {
		t.Fatalf("addition: %q", got)
	}
}

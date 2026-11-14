package main

import (
	"reflect"
	"testing"
	"time"

	"github.com/Ziegfe1d/VWARD/tools/vward-core/internal/adaptive"
)

// «Реклама и счётчики мимо VPN» in the sandbox (owner 13.11.2026): off - not a line; switched to the
// sandbox - one line of the mode and every ad name of the group once; nothing repeats at the next
// rounds; switched off - one line.
func TestAdsRoundLines(t *testing.T) {
	var got [][3]string
	put := func(code, host, detail string) { got = append(got, [3]string{code, host, detail}) }
	owned := []string{"chatgpt.com", "stats.g.doubleclick.net", "api.mixpanel.com"}
	ads, now := &adaptive.AdsSandbox{}, time.Now()
	adsRound(ads, adaptive.AdsOff, owned, now, put)
	if len(got) != 0 {
		t.Fatalf("off writes nothing: %v", got)
	}
	adsRound(ads, adaptive.AdsShadow, owned, now, put)
	adsRound(ads, adaptive.AdsShadow, owned, now, put)
	adsRound(ads, adaptive.AdsShadow, append(owned, "ad.doubleclick.net"), now, put)
	adsRound(ads, adaptive.AdsOff, owned, now, put)
	adsRound(ads, adaptive.AdsOff, owned, now, put)
	want := [][3]string{
		{"ADS_MODE", "shadow", ""},
		{"WOULD_REMOVE_AD", "api.mixpanel.com", "zone=api.mixpanel.com"},
		{"WOULD_REMOVE_AD", "stats.g.doubleclick.net", "zone=doubleclick.net"},
		{"WOULD_REMOVE_AD", "ad.doubleclick.net", "zone=doubleclick.net"},
		{"ADS_MODE", "off", ""},
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("sandbox lines:\n got %v\nwant %v", got, want)
	}
}

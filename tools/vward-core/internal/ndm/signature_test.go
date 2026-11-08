package ndm

import (
	"os"
	"os/exec"
	"path/filepath"
	"testing"
)

// The ownership proof must be byte-identical to what the shell core stored in
// services/owned/GROUP: service_signature_raw | service_canonical of
// vward-console-config.sh, copied here verbatim and run by sh.
const shellSignature = `
RUNCFG=$1
group_routes() {
    awk -v g="$1" '/^[^ \t!]/ {ctx=($1=="dns-proxy" && NF==1)} /^!/ {ctx=0}
        ctx && $1=="route" && $2=="object-group" && $3==g {
            o=""; for(k=5;k<=NF;k++) o=o (o==""?"":" ") $k
            print $4 "\t" (o==""?"-":o)
        }' "$RUNCFG" | sort
}
service_canonical() {
    awk '/^description "/ && /"$/ {
        d=substr($0,14,length($0)-14)
        if (d !~ /["\\\\]/) $0="description " d
    } {print}' | sort
}
service_signature_raw() {
    { awk -v g="$1" '/^object-group fqdn / {cur=$3; next} /^!/ {cur=""}
          cur==g {sub(/^[[:space:]]+/, ""); if (NF) print}' "$RUNCFG"
      group_routes "$1" | sed 's/^/route=/'
    } | sort
}
service_signature_raw "$2" | service_canonical
`

func TestSignatureParity(t *testing.T) {
	cfg := `object-group fqdn domain-list7
    description "YouTube"
    include youtube.com
    include googlevideo.com
    exclude ads.youtube.com
!
object-group fqdn domain-list8
    description "Claude AI"
    include claude.ai
!
object-group fqdn domain-list9
!
dns-proxy
    route object-group domain-list7 OpkgTun4 auto
    route object-group domain-list7 Wireguard1
    route object-group domain-list8 OpkgTun2 auto
    https upstream https://x dnsm on ISP domain a.example
!
`
	dir := t.TempDir()
	p := filepath.Join(dir, "running")
	os.WriteFile(p, []byte(cfg), 0o600)
	m := ParseRunning(cfg)
	for _, sh := range [][]string{{"sh"}, {"busybox", "ash"}} {
		if _, err := exec.LookPath(sh[0]); err != nil {
			continue
		}
		for _, g := range []string{"domain-list7", "domain-list8", "domain-list9"} {
			cmd := exec.Command(sh[0], append(sh[1:], "-c", shellSignature, "sig", p, g)...)
			cmd.Env = append(os.Environ(), "LC_ALL=C")
			want, err := cmd.Output()
			if err != nil {
				t.Fatal(err)
			}
			got, _ := m.Signature(g)
			if got != string(want) {
				t.Fatalf("%v %s:\nshell %q\ngo    %q", sh, g, want, got)
			}
			if CanonicalSignature(string(want)) != got {
				t.Fatalf("%s: canonical of the stored proof differs", g)
			}
		}
	}
}

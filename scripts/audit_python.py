import httpx
import json
import re

packages = []
with open("requirements.lock", "r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = re.split(r"==|>=|<=|~=", line)
        if len(parts) >= 2:
            pkg_name = parts[0].strip()
            pkg_ver = parts[1].strip()
            packages.append((pkg_name, pkg_ver))

print(f"Auditing {len(packages)} packages via OSV with httpx...")
queries = [{"package": {"name": name, "ecosystem": "PyPI"}, "version": ver} for name, ver in packages]

client = httpx.Client(timeout=30.0)
try:
    resp = client.post("https://api.osv.dev/v1/querybatch", json={"queries": queries})
    resp.raise_for_status()
    data = resp.json()
    findings = []
    results = data.get("results", [])
    for (name, ver), res in zip(packages, results):
        vulns = res.get("vulns", [])
        for v in vulns:
            vid = v.get("id")
            summary = v.get("summary", "")
            database_specific = v.get("database_specific", {})
            ghsa_sev = database_specific.get("severity")
            if not ghsa_sev:
                for s in v.get("severity", []):
                    ghsa_sev = s.get("score")
            findings.append({
                "package": name,
                "version": ver,
                "id": vid,
                "severity": ghsa_sev or "UNKNOWN",
                "summary": summary
            })

    out_path = "docs/s25_evidence/a7_pip_audit.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(findings, f, indent=2)

    txt_path = "docs/s25_evidence/a7_pip_audit.txt"
    lines = [
        f"Audited {len(packages)} Python packages from requirements.lock via OSV batch API.",
        f"Total vulnerabilities found: {len(findings)}"
    ]
    high_crit = [f for f in findings if str(f.get("severity")).upper() in ("HIGH", "CRITICAL")]
    lines.append(f"High / Critical vulnerabilities: {len(high_crit)}")
    for hc in high_crit:
        lines.append(f"  [{hc['severity']}] {hc['package']}=={hc['version']}: {hc['id']} - {hc['summary']}")

    out_txt = "\n".join(lines) + "\n"
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(out_txt)
    print(out_txt)
except Exception as e:
    print(f"Failed to query OSV batch: {e}")
finally:
    client.close()

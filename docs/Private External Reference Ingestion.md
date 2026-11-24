# Private external reference ingestion (candidate)

This adds a local-only store for Damodaran, CRA, OCC and NIST reference
snapshots. Official reference texts are not executable instructions, financial
evidence, or proof of competence. The public model never receives this raw text.
Role dispatch automatically searches the store and records snapshot IDs and
excerpt hashes; the existing deterministic handlers remain unchanged. Local
operator retrieval returns actual text. Use the existing independently reviewed
role memory workflow for cloud-eligible derived annotations; no automatic
learning or skill promotion is added here.

NIST offers a machine-readable AI RMF Playbook at
https://airc.nist.gov/docs/playbook.json, linked by
https://airc.nist.gov/airmf-resources/playbook/. Its copyright policy is
https://www.nist.gov/copyrights-disclaimers. The fixed URL downloader requires
an explicit local rights policy and network opt-in; it rejects redirects and
limits the response size. The playbook is voluntary guidance, not certification.

For the other sources, obtain rights-cleared material and extract plain UTF-8
text locally. Do not commit copyrighted material or private reference DBs.
Consult https://www.canada.ca/en/transparency/terms.html,
https://www.theocc.com/specialpages/legal/terms-and-conditions, and the
specific Damodaran material's conditions before importing. The policy is an
operator attestation, not an automated license determination.

Example private NIST policy (verify rights before use):

```json
{"source_id":"nist","source_url":"https://airc.nist.gov/docs/playbook.json","rights_reviewed":true,"allow_local_retention":true,"allow_local_rag":true,"cloud_allowed":false,"license_note":"NIST official playbook; reviewed applicable copyright exceptions and third-party material before local retention."}
```

```bash
atlas-reference --data-dir /private/atlas fetch-nist --policy /private/nist-policy.json --network
atlas-reference --data-dir /private/atlas import --file /private/rights-cleared-reference.txt --policy /private/reference-policy.json
atlas-reference --data-dir /private/atlas search A105 "model risk evaluation"
```

Source access is inherited from the existing role source catalog. Retrieval
uses the latest locally received version as of the task cutoff and filters
roles before lexical ranking. Historical first-availability is not inferred.
Updates preserve previous snapshots. SQLite integrity hashes are not
cryptographic provenance proof against a malicious local administrator.
Storage is bounded, private and local; an operator must stop using revoked
content and manage retention separately. No scheduled download is installed.
No live download, full professional competence, or paid model evaluation was
verified by the developer tests. FinanceBench is explicitly excluded.

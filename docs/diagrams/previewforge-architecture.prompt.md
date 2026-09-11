# PreviewForge architecture image prompts

Generated using the built-in imagegen tool on 2026-09-10. Output: `previewforge-architecture.png` (1536 × 1024 PNG). This is a raster diagram in the style of draw.io, not an editable `.drawio` document. The two PR numbers are examples. No credentials were included in these prompts.

## Initial generation

Use case: infographic-diagram.
Create one polished, technically accurate project architecture IMAGE for PreviewForge, in the style of a carefully arranged diagrams.net / draw.io architecture diagram. This is a documentation figure for a developer, not an illustration or screenshot of an editor. Wide landscape canvas, high resolution, pure white background, very crisp readable typography, restrained pastel containers, thin dark borders, flat simple technology icons, orthogonal connectors with arrowheads and short labels, generous whitespace. No 3D, gradients, decorative scenery, fake UI, watermark, or invented components. All text in English with precise spelling. Use a strong visual hierarchy and prioritize legibility over extra text.

Title: "PreviewForge"
Subtitle: "Project architecture · One private repository · Local PR environments"

Organize into two clear outer boundaries:
A. A shallow top boundary named "EXTERNAL SERVICES".
B. A large lower boundary named "DEVELOPER LAPTOP · Docker Desktop", containing host tools, Floci and a nested "kind · Local Kubernetes" boundary.

EXTERNAL SERVICES:
- A GitHub repository box labeled "HickoDev / PreviewForge" and "Private repository". Show two internal sections "Application source + PRs" and "GitOps records + Helm charts". These are parts of ONE repository, not separate repositories.
- A box "GitHub Actions" with small lines "Test + build" and "Trusted delivery". Source PRs point to Actions with label "PR / merge". Actions points to GHCR with label "Publish". Actions also points BACK to the repository's GitOps section with label "Write image digest".
- A box "GHCR" with subtitle "Private, immutable images".
- A separate purple-accent box "NVIDIA hosted NIM" with small subtitle "Nemotron 3 Super". Keep this outside the laptop and outside kind. It connects only to the trusted assistant described below.

HOST TOOLS inside laptop, outside kind:
- "Local watcher" with subtitle "gh · HickoDev", and small text "Namespaces · secrets · cleanup". It reads the repository GitOps records via a dashed connector labeled "Poll desired state". Polling is initiated locally; do not depict an inbound webhook or public tunnel.
- Below the watcher: "Terraform" with subtitle "Per-environment resources". Watcher points to Terraform with label "Reconcile".
- An orange box "Floci" with subtitle "Simulated AWS · local endpoints". Inside it, two simple icons "S3 buckets" and "SQS queues". Terraform points to Floci labeled "Provision / clean up". Small line "Separate bucket + queue per environment". Floci runs in Docker Desktop OUTSIDE the kind cluster, not in AWS. A tiny footnote in this box: "Dummy AWS credentials".
- A simple small box "Browser / API client" with subtitle "127.0.0.1 port-forwards", linked to the environment APIs. Include readable URL-port labels associated with the three environment cards: staging 18000, PR #123 18051, PR #124 18052. These are example active PR numbers, not domain names.

KIND CLUSTER:
- At the top, a box "Argo CD + ApplicationSet", subtitle "Render Helm · sync · self-heal". A dashed GitOps connector between the GitOps repository section and Argo is labeled "Pull desired state". Argo points to the environment group with label "Reconcile workloads". The watcher points to the namespace boundary with label "Prepare namespaces".
- Main environment group: THREE equally sized adjacent namespace cards named "staging", "preview-123", "preview-124". Each card must visibly contain these exact component labels: "FastAPI", "Export worker", "PostgreSQL + PVC". Use a database cylinder icon for each PostgreSQL. Within each card, FastAPI and worker both connect to that card's own PostgreSQL, not another namespace's database. Small shared subtitle above the group: "Isolated application data per environment". Below each card, respectively "localhost:18000", "localhost:18051", "localhost:18052".
- GHCR points to this environment group via a connector labeled "Kubernetes pulls by digest". Do not make Argo pull/run images.
- A clean orange connector from the environment group to Floci with label "Export jobs · SQS / S3". A small adjacent two-line annotation says "API queues jobs → worker writes reports" and "API downloads reports". Do not draw real AWS.
- A green observability group with namespace label "observability". Boxes "Prometheus" and "Grafana" connected so metrics flow from environment group into Prometheus ("Metrics"), and from Prometheus into Grafana ("Query / visualize"). Small text "localhost:13000". Prometheus also observes Kubernetes / Argo state; a small label or short connector is enough.
- A purple trusted assistant group with namespace label "previewforge-ai". Main box "Diagnostic assistant" with sublabels "Collect → sanitize → infer → validate" and "Mock or explicit live mode". It reads scoped deployment state and logs from approved environments using a dashed purple connector labeled "Read-only evidence". A bidirectional purple connector to EXTERNAL NVIDIA NIM says "HTTPS · sanitized evidence / diagnosis". It does not deploy, roll back or run commands. Small label within the group: "Cited facts + hypotheses". Small lock icon label "Local Kubernetes Secret". Small text "localhost:18080".
- Show the environment group and observability and assistant as distinct namespace areas; do not place the assistant inside a PR namespace.

At the bottom, an understated legend with blue "Delivery / GitOps", orange "Export data", green "Metrics", purple "Diagnostics". Short footer: "PR close → preview cleanup · Floci simulates S3/SQS · Local services only".
Add a small unobtrusive status note: "AI live smoke verified; full quality evaluation pending."

Accuracy is more important than decorative density. Avoid crossing edges through text or node interiors. Use a consistent flow and tidy routing. Keep all major labels large enough to read in the full image. Avoid duplicating node names as floating labels. Do not include commands, credentials, API keys, real secret values, cloud provisioning, ingress, EKS, LocalStack, a second remote repository or an autonomous AI remediation arrow.

## Connector correction

Edit this architecture diagram. Preserve its layout, all component boxes, typography, colors, icons, title, footer, and all correct connections. Make ONLY these technical connector corrections, using clean orthogonal lines with no arrows through text:
1. The blue connector labeled "Kubernetes pulls by digest" currently ends on top of the "Argo CD + ApplicationSet" box. This is INCORRECT. Reroute it from the GHCR box to the outer "Application environments (namespaces)" group, ending on that group's upper-right border. Route around the RIGHT edge of the Argo box; no blue image-pull arrow may terminate on Argo. Keep the separate Argo-to-environments "Reconcile workloads" arrow.
2. Remove the short purple horizontal arrow from Prometheus to Diagnostic assistant. Prometheus is not a data source for this assistant. Preserve the green metrics and Grafana arrows.
3. Add one dashed purple connector from the application environment group to the "previewforge-ai" namespace box, labeled "Deployment state + logs". Route it along the free space just above the namespace cards and observability box; do not pass through Argo, Prometheus or Grafana. Keep the existing dashed Argo-to-assistant "Read-only evidence" connection because the assistant ALSO reads Argo application state.
4. In the "Local watcher" box, replace its lowest text line with "Poll Git · namespaces · secrets · cleanup". Do not alter its title or the gh/HickoDev identity line.
Everything else unchanged. The result must remain a beautiful readable draw.io-style architecture diagram.

## Final correction

Make one precise correction to this diagram and preserve EVERYTHING ELSE exactly.
Remove the ENTIRE blue outgoing connector that starts at the RIGHT edge of the GHCR box, turns downward, then turns left to a floating arrow above the Argo CD box. Also remove its floating label "Kubernetes pulls by digest". Erase all three segments and its arrowhead cleanly, restoring the plain background.
Keep the incoming "Publish" arrow from GitHub Actions into GHCR.
Inside the GHCR box, replace the small subtitle "Private, immutable images" with two small readable lines:
"Private, immutable images"
"Pulled by kind nodes"
There should now be NO outgoing blue connector from GHCR. The subtitle explains its consumer clearly. Do not add a replacement arrow. Do not alter any other connector, text, component, layout, size, or colors.

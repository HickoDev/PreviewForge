# PreviewForge architecture diagrams

Open **[previewforge-architecture.drawio](previewforge-architecture.drawio)** in draw.io Desktop to edit the architecture. It is an uncompressed native draw.io document with three pages, grouped components and attached orthogonal connectors. It includes technology logos and native Kubernetes/AWS resource symbols. The logos are embedded SVGs; there are no raster pictures or external image dependencies.

| Page | Scope | Vector export | Image export |
| --- | --- | --- | --- |
| 01 — Platform overview | GitHub delivery, host tools, kind environments, Floci, observability and optional NVIDIA inference | [SVG](previewforge-architecture-overview.svg) | [PNG](previewforge-architecture-overview.png) |
| 02 — PR delivery and cleanup | Trusted build publication, Git records, independent controllers and ordered preview removal | [SVG](previewforge-architecture-delivery.svg) | [PNG](previewforge-architecture-delivery.png) |
| 03 — Runtime, exports and diagnostics | Database outbox, worker/queue/report flow, metrics and scoped diagnostic evidence | [SVG](previewforge-architecture-runtime.svg) | [PNG](previewforge-architecture-runtime.png) |

[Download all three pages as PDF](previewforge-architecture.pdf). Use the overview PNG for an image upload, the PDF for a document post, and SVG for scaling without loss of sharpness. PNG exports are 2,882 pixels wide. SVG and PDF exports also embed the editable diagram.

## PNG previews

These are the latest draw.io exports, in the same order as the three-page PDF.

### 01 — Platform overview

![Platform overview](previewforge-architecture-overview.png)

### 02 — PR delivery and cleanup

![PR delivery and cleanup](previewforge-architecture-delivery.png)

### 03 — Runtime, exports and diagnostics

![Runtime, exports and diagnostics](previewforge-architecture-runtime.png)

## Editing and export

1. Open the `.drawio` file with draw.io Desktop on your OS, or use **File → Open From → Device** in diagrams.net.
2. Select a page using the bottom tabs. Double-click text to edit it; move a component or its containing group to keep related objects together.
3. Save the `.drawio` source, then export the updated pages. Check the images at normal size for clipped labels and connector crossings.

### Where to find the symbols

In draw.io, click **More Shapes…** at the bottom of the left sidebar and enable **Kubernetes** and **AWS**. Those libraries include namespace, pod, volume, queue and bucket symbols. The S3 and SQS symbols in this architecture describe Floci's simulated services.

For the exact symbols used here, open **File → Open Library from → Device** and select **[previewforge-symbols.xml](previewforge-symbols.xml)**. This adds a reusable 28-symbol palette to the sidebar: the project technology logos, Kubernetes resources, S3/SQS, a registry cube and an input-filter symbol. Drag symbols into the diagram as needed.

Brand artwork comes from the pinned [Simple Icons source](icons/sources.json): Docker, Kubernetes, Terraform, PostgreSQL, Prometheus, Grafana, NVIDIA, FastAPI, GitHub, GitHub Actions, Git, Argo and Helm. The original SVGs and [upstream license](icons/SIMPLE-ICONS-LICENSE.md) are retained in `icons/`; brand colors are applied in the embedded copies. Kubernetes and AWS resource symbols use draw.io's built-in libraries. The registry cube and input filter are generic diagram symbols.

### Regenerate the exports

These PowerShell commands were verified on Windows with draw.io Desktop **30.0.0**. On other hosts, use the desktop export menu; a Linux CLI export has not been verified. Run from the repository root. They regenerate the existing exports from the editable source:

```powershell
$drawio = 'C:\Program Files\draw.io\draw.io.exe'
$source = Join-Path (Get-Location).Path 'docs\diagrams\previewforge-architecture.drawio'
$names = @('overview', 'delivery', 'runtime')

for ($page = 1; $page -le 3; $page++) {
    $base = Join-Path (Get-Location).Path ('docs\diagrams\previewforge-architecture-' + $names[$page - 1])
    Start-Process -FilePath $drawio -WindowStyle Hidden -Wait -ArgumentList @(
        '--disable-update', '--export', '--format', 'png', '--scale', '1.5',
        '--page-index', $page, '--output', ('"' + $base + '.png"'), ('"' + $source + '"')
    )
    Start-Process -FilePath $drawio -WindowStyle Hidden -Wait -ArgumentList @(
        '--disable-update', '--export', '--format', 'svg', '--svg-theme', 'light',
        '--embed-svg-fonts', 'false', '--embed-diagram', '--page-index', $page,
        '--output', ('"' + $base + '.svg"'), ('"' + $source + '"')
    )
}

$pdf = Join-Path (Get-Location).Path 'docs\diagrams\previewforge-architecture.pdf'
Start-Process -FilePath $drawio -WindowStyle Hidden -Wait -ArgumentList @(
    '--disable-update', '--export', '--format', 'pdf', '--all-pages', '--crop',
    '--embed-diagram', '--output', ('"' + $pdf + '"'), ('"' + $source + '"')
)
```

The diagrams describe the configured GitHub mode, not the original local Git fixture. PR numbers and preview ports are examples. Native file structure, text fit, PNG/SVG exports and the three-page PDF were checked against the application and platform documentation. The `.drawio` file is the maintained diagram source; the architecture previews use only its three current PNG exports.

# Hardware

This directory contains the mechanical, electrical, and manufacturing files for
the modular laboratory robot.

## Structure

- `mechanical/`: original CAD, neutral STEP exports, and print-ready STL files.
- `electronics/`: schematics, PCB design files, and wiring documentation.
- `bom/`: bills of materials and sourcing information.
- `third-party/`: attribution and licence records for externally sourced models.

Each mechanical assembly uses the same export structure:

```text
assembly-name/
|-- source/  # Editable native CAD, such as F3D
|-- step/    # Neutral CAD exchange files
`-- stl/     # Current print-ready parts
```

Use descriptive lowercase filenames with hyphens. Git records normal design
history, so avoid names such as `final-final` unless two revisions must remain
available at the same time.

Original hardware files should use the hardware licence declared by the
repository. Do not add third-party models until their source, author, licence,
and modification status have been recorded in `third-party/README.md`.

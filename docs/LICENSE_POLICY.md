# License Policy

## Current Repository License

The software, firmware source, scripts, documentation, and templates in this repository are licensed under Apache License 2.0 unless a file or module declares a different license.

See the root `LICENSE` file.

## Why Apache-2.0 For Software

Apache-2.0 is permissive, widely understood, and includes an explicit patent grant. That is useful for an open robotics platform where labs, universities, startups, and individual builders may all need to use, modify, and redistribute the software.

## Future Hardware/CAD Licensing

Future hardware modules may include:

- electronics designs
- wiring diagrams
- PCB files
- mechanical CAD
- 3D-printable parts
- simulation geometry

Those hardware artifacts should carry their own explicit license. Preferred default:

```text
CERN-OHL-S-2.0
```

Use that when the project wants hardware improvements and derivative designs to stay open. If a future module needs a different hardware license, document the reason in that module.

## Community Module Licensing

Every future module package should declare:

- software license
- hardware/CAD license if applicable
- documentation license if different
- third-party asset licenses

The module importer should eventually reject or warn on packages with missing or incompatible license metadata.

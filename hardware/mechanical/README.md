# Mechanical Design

Mechanical files are grouped by robot assembly. Keep editable CAD in `source/`,
neutral exports in `step/`, and only current print-ready meshes in `stl/`.
The `whole-robot/` directory contains the maintained partial assembly that brings
the major subsystems together.

When adding a part, record its quantity, material, print orientation, support
requirements, and assembly notes in the relevant assembly directory.

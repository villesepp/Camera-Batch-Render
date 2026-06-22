# Camera Batch Render

<img width="655" height="445" alt="image" src="https://github.com/user-attachments/assets/4c2b9ccf-1216-4024-bcce-059c62c13647" />

Camera Batch Render is a Blender add-on for rendering still images and frame
ranges from multiple cameras in one batch. Camera names can define per-camera
resolution and frame ranges, while the Render Properties panel controls filtering,
output, overwrite behavior, progress, and cancellation.

**Current version:** 1.8.2  
**Minimum Blender version:** 3.6

## Features

- Render every matching camera in the current scene.
- Set independent default width and height values.
- Override resolution through camera-name prefixes.
- Render inclusive frame ranges defined in camera names.
- Filter by selected cameras or chosen scene collections.
- Exclude cameras whose names begin with an underscore.
- Skip existing files by default, with optional overwriting.
- Avoid filename collisions within the current batch.
- Show live image count, progress, and a cancel button.
- Open the output directory in the system file explorer.
- Copy a selected camera's parsed resolution to Output Properties.
- Show a post-batch report for rendered, excluded, invalid, and skipped items.

---

## Development Note

This was developed with assistance from generative AI for planning, code iteration, debugging, and documentation. The project was manually tested in Blender 4.5.5 and 5.1.2.

---

## Installation

1. Download **camera_batch_render.py**.
2. In Blender, open **Edit > Preferences > Add-ons**.
3. Choose **Install from Disk** and select **camera_batch_render.py**.
4. Enable **Camera Batch Render**.
5. Open **Properties > Render Properties > Camera Batch Render**.

When updating, disable or remove the previous installed version before installing
the new file if Blender does not replace it automatically.

## Quick Start

1. Set the default **Width** and **Height**.
2. Choose an **Output** directory.
3. Optionally enable camera or collection filters.
4. Name cameras with resolution or frame-range prefixes as needed.
5. Click **Images to render: N**.
6. Review the batch report after rendering finishes.

The image count includes every frame produced by ranged cameras.

## Camera Naming Syntax

Metadata tokens are read from the beginning of the camera object name. Tokens are
case-insensitive and should appear before the descriptive filename.

This picture demonstrates various ways how to name the cameras in order to get a different render result:

<img width="641" height="344" alt="image" src="https://github.com/user-attachments/assets/ca8bd164-87ba-417a-bd36-129925374056" />

### Resolution

| Camera name | Resolution |
| --- | --- |
| **Camera** | Default width x default height |
| **512 Camera** | 512 x 512 |
| **w512 Camera** | 512 x default height |
| **h256 Camera** | Default width x 256 |
| **w512 h256 Camera** | 512 x 256 |

A bare square size must begin with at least two digits. Parenthesized forms such
as **w(512)** and **h(256)** are also accepted, but the shorter form is
recommended.

### Frame Ranges

Use **b** for the beginning frame and **e** for the ending frame:

| Camera name | Result |
| --- | --- |
| **b1 e10 Camera** | Render timeline frames 1 through 10 |
| **w512 h256 b20 e24 Camera** | Render frames 20 through 24 at 512 x 256 |
| **b-5 e5 Camera** | Render frames -5 through 5 |
| **b10 Camera** | Skipped because the end frame is missing |
| **e10 Camera** | Skipped because the begin frame is missing |
| **b10 e5 Camera** | Skipped because the range is reversed |

Ranges are inclusive. Parenthesized forms such as **b(1)** and **e(10)** are
also accepted.

By default, ranged files use their timeline frame number:

~~~text
Camera_10.png
Camera_11.png
Camera_12.png
~~~

Enable **Start Range File Numbers at 1** to render the same timeline frames while
numbering the files from 1:

~~~text
Camera_1.png
Camera_2.png
Camera_3.png
~~~

## Camera Filters

### Selected Cameras Only

Renders camera objects that are currently selected.

### Selected Collections Only

Displays a collection checklist in the add-on panel. Cameras are rendered only
when they belong to a checked collection. Checking a parent collection also
includes its nested collections.

**Selected Cameras Only** and **Selected Collections Only** are mutually
exclusive. Enabling one automatically disables the other.

### Exclude Cameras Beginning with "_"

Skips cameras whose object names begin with an underscore. This can be combined
with either selection filter.

## Output and Filename Rules

The output filename is derived from the camera object name:

1. Resolution and frame-range prefixes are removed.
2. A period and everything following it are removed.
3. Characters invalid in Windows filenames are removed.
4. Invalid or empty results fall back to a cleaned original object name.
5. Windows reserved filenames such as **CON** and **NUL** are avoided.
6. Duplicate names in one batch receive **_001**, **_002**, and later suffixes.
7. Ranged renders append their chosen frame number.

Render result report:

<img width="413" height="420" alt="image" src="https://github.com/user-attachments/assets/5e4ce8dd-1e8c-456d-b7fa-f2883456058d" />

Rendered images generated by the add-on (the Blender project file is not generated):

<img width="592" height="563" alt="image" src="https://github.com/user-attachments/assets/bc590f51-bab0-4c96-8ad3-f5a1ee18a1eb" />

The scene's current render engine, file format, color settings, and other render
settings are used.

Existing output files are skipped by default. Enable **Overwrite Existing
Images** to replace files from earlier batches. Files generated earlier in the
same batch are never overwritten.

The default output path is **//renders/**, which is relative to the saved Blender
file. Saving the Blender file before using relative paths is recommended.

## Controls

- **Width / Height:** Default resolution when a camera name does not override it.
- **Set Output Resolution from Selected Camera:** Copies the selected camera's
  parsed resolution to **Output Properties > Resolution X/Y**.
- **Output:** Selects the render directory.
- **Output icon button:** Opens the directory in the system file explorer.
- **Images to render: N:** Starts the batch and shows the total task count.
- **Progress:** Shows completed render tasks while a batch is running.
- **Cancel Batch:** Stops after the current individual render finishes.
- **Quick Help:** Displays a compact naming and usage reference.

## Batch Report

After a batch, the report lists rendered image filenames. Additional sections
appear only when relevant:

- Excluded cameras
- Invalid frame-range warnings
- Files skipped because they already existed
- Cancellation or render errors

## Scene Restoration

After a completed, cancelled, or failed batch, the add-on restores:

- Active scene camera
- Render output filepath
- Resolution X and Y
- Resolution percentage
- Current timeline frame

## Limitations

- The cancel button takes effect between individual renders. Blender remains busy
  while a single image is rendering.
- Camera metadata must be at the beginning of the object name.
- A camera with only **b** or only **e**, or a begin frame after its end frame, is
  skipped entirely.
- Very large frame ranges create correspondingly large render queues.

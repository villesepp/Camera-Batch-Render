bl_info = {
    "name": "Camera Batch Render",
    "author": "OpenAI",
    "version": (1, 8, 2),
    "blender": (3, 6, 0),
    "location": "Properties > Render > Camera Batch Render",
    "description": "Render images from every matching camera in the scene",
    "category": "Render",
}

import os
import re

import bpy
from bpy.props import BoolProperty, IntProperty, PointerProperty, StringProperty
from bpy.types import Operator, Panel, PropertyGroup


LEADING_SQUARE_PATTERN = re.compile(r"^(\d{2,})")
PREFIX_TOKEN_PATTERN = re.compile(
    r"\s*([wheb])\s*(?:\(\s*(-?\d+)\s*\)|(-?\d+))",
    re.IGNORECASE,
)
WINDOWS_INVALID_CHARS = '<>:"/\\|?*'
WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


def collection_tree(root):
    collections = [root]
    for child in root.children:
        collections.extend(collection_tree(child))
    return collections


def selected_collection_pointers(scene):
    selected = set()
    for collection in collection_tree(scene.collection):
        if collection.render_every_camera_selected:
            selected.update(item.as_pointer() for item in collection_tree(collection))
    return selected


def camera_selection(
    scene,
    selected_only,
    exclude_underscore=False,
    selected_collections_only=False,
):
    included = []
    excluded = []
    collection_pointers = (
        selected_collection_pointers(scene) if selected_collections_only else set()
    )
    for camera in (obj for obj in scene.objects if obj.type == "CAMERA"):
        is_excluded = selected_only and not camera.select_get()
        is_excluded |= exclude_underscore and camera.name.startswith("_")
        if selected_collections_only:
            is_excluded |= not any(
                collection.as_pointer() in collection_pointers
                for collection in camera.users_collection
            )
        (excluded if is_excluded else included).append(camera)

    sort_key = lambda obj: obj.name.casefold()
    return sorted(included, key=sort_key), sorted(excluded, key=sort_key)


def parse_camera_metadata(camera_name, default_width, default_height):
    width = default_width
    height = default_height
    begin_frame = None
    end_frame = None
    position = 0
    prefix_end = 0

    square_match = LEADING_SQUARE_PATTERN.match(camera_name)
    if square_match:
        size = max(1, int(square_match.group(1)))
        width = size
        height = size
        position = square_match.end()
        prefix_end = position

    while True:
        token_match = PREFIX_TOKEN_PATTERN.match(camera_name, position)
        if not token_match:
            break

        axis = token_match.group(1).lower()
        value = int(token_match.group(2) or token_match.group(3))
        if axis == "w":
            width = max(1, value)
        elif axis == "h":
            height = max(1, value)
        elif axis == "b":
            begin_frame = value
        else:
            end_frame = value

        position = token_match.end()
        prefix_end = position

    invalid_range = None
    if (begin_frame is None) != (end_frame is None):
        missing = "end" if end_frame is None else "begin"
        invalid_range = f"missing {missing} frame"
    elif (
        begin_frame is not None
        and end_frame is not None
        and begin_frame > end_frame
    ):
        invalid_range = (
            f"begin frame {begin_frame} is after end frame {end_frame}"
        )

    return (
        width,
        height,
        begin_frame,
        end_frame,
        prefix_end,
        invalid_range,
    )


def parse_camera_resolution(camera_name, default_width, default_height):
    width, height, _begin, _end, prefix_end, _invalid = parse_camera_metadata(
        camera_name, default_width, default_height
    )
    return width, height, prefix_end


def build_render_tasks(cameras, settings):
    tasks = []
    invalid_ranges = []
    for camera in cameras:
        (
            width,
            height,
            begin_frame,
            end_frame,
            _prefix_end,
            invalid_range,
        ) = parse_camera_metadata(
            camera.name,
            settings.default_width,
            settings.default_height,
        )

        if invalid_range:
            invalid_ranges.append((camera.name, invalid_range))
            continue

        if begin_frame is None:
            tasks.append((camera, width, height, None, None))
            continue

        for sequence_number, frame in enumerate(
            range(begin_frame, end_frame + 1), start=1
        ):
            tasks.append((camera, width, height, frame, sequence_number))

    return tasks, invalid_ranges


def strip_windows_invalid(name):
    return "".join(
        char for char in name if char not in WINDOWS_INVALID_CHARS and ord(char) >= 32
    ).rstrip(". ")


def is_valid_windows_stem(name):
    return bool(name) and name.split(".", 1)[0].upper() not in WINDOWS_RESERVED_NAMES


def camera_filename(camera_name):
    _width, _height, _begin, _end, prefix_end, _invalid = parse_camera_metadata(
        camera_name, 1, 1
    )
    candidate = camera_name[prefix_end:].split(".", 1)[0]
    candidate = strip_windows_invalid(candidate).strip()
    if not is_valid_windows_stem(candidate):
        candidate = strip_windows_invalid(camera_name).strip()
    return candidate if is_valid_windows_stem(candidate) else "Camera"


def frame_filename_number(number):
    return str(number)


def unique_output_path(folder, stem, extension, used_paths):
    suffix = 0
    while True:
        numbered_stem = stem if suffix == 0 else f"{stem}_{suffix:03d}"
        base_path = os.path.join(folder, numbered_stem)
        final_path = base_path + extension
        normalized = os.path.normcase(os.path.abspath(final_path))
        if normalized not in used_paths:
            used_paths.add(normalized)
            return base_path, os.path.basename(final_path)
        suffix += 1


def selected_camera(context):
    selected = [
        obj for obj in context.scene.objects
        if obj.type == "CAMERA" and obj.select_get()
    ]
    active = context.view_layer.objects.active
    if active in selected:
        return active
    return selected[0] if len(selected) == 1 else None


def tag_properties_redraw(context):
    if context.screen:
        for area in context.screen.areas:
            if area.type == "PROPERTIES":
                area.tag_redraw()


def update_selected_cameras_only(settings, _context):
    if settings.selected_only:
        settings.selected_collections_only = False


def update_selected_collections_only(settings, _context):
    if settings.selected_collections_only:
        settings.selected_only = False


class RENDER_EVERY_CAMERA_Settings(PropertyGroup):
    default_width: IntProperty(
        name="Default Width", default=1024, min=1, soft_max=8192, subtype="PIXEL",
    )
    default_height: IntProperty(
        name="Default Height", default=1024, min=1, soft_max=8192, subtype="PIXEL",
    )
    output_folder: StringProperty(
        name="Output Folder", default="//renders/", subtype="DIR_PATH",
    )
    selected_only: BoolProperty(
        name="Selected Cameras Only",
        default=False,
        update=update_selected_cameras_only,
    )
    exclude_underscore: BoolProperty(
        name='Exclude Cameras Beginning with "_"', default=False,
    )
    selected_collections_only: BoolProperty(
        name="Selected Collections Only",
        default=False,
        update=update_selected_collections_only,
    )
    overwrite_existing: BoolProperty(
        name="Overwrite Existing Images", default=False,
    )
    range_numbers_from_one: BoolProperty(
        name="Start Range File Numbers at 1",
        description=(
            "Number ranged output files from 1 instead of using timeline frames"
        ),
        default=False,
    )
    batch_running: BoolProperty(default=False, options={"HIDDEN"})
    cancel_requested: BoolProperty(default=False, options={"HIDDEN"})
    progress: IntProperty(
        name="Progress", default=0, min=0, max=100, subtype="PERCENTAGE",
    )


class RENDER_EVERY_CAMERA_OT_quick_help(Operator):
    bl_idname = "render_every_camera.quick_help"
    bl_label = "Camera Batch Render - Quick Help"

    def execute(self, context):
        def draw_help(menu, _context):
            layout = menu.layout
            layout.label(text="Square: 512 Camera")
            layout.label(text="Rectangle: w512 h256 Camera")
            layout.label(text="Range: b1 e10 Camera")
            layout.label(text="Combine tokens: w512 h256 b1 e10 Camera")
            layout.label(text="Both b and e are required; ranges include both bounds.")
            layout.label(text="Existing files are skipped unless overwrite is enabled.")
            layout.label(text="Cancel takes effect between individual renders.")

        context.window_manager.popup_menu(
            draw_help, title="Quick Help", icon="QUESTION"
        )
        return {"FINISHED"}


class RENDER_EVERY_CAMERA_OT_apply_selected_resolution(Operator):
    bl_idname = "render_every_camera.apply_selected_resolution"
    bl_label = "Set Output Resolution from Selected Camera"

    def execute(self, context):
        camera = selected_camera(context)
        if camera is None:
            self.report({"WARNING"}, "Select one camera, or make one selected camera active")
            return {"CANCELLED"}
        settings = context.scene.render_every_camera
        width, height, _prefix_end = parse_camera_resolution(
            camera.name, settings.default_width, settings.default_height
        )
        context.scene.render.resolution_x = width
        context.scene.render.resolution_y = height
        self.report({"INFO"}, f"Output set to {width} x {height} from {camera.name}")
        return {"FINISHED"}


class RENDER_EVERY_CAMERA_OT_open_output_folder(Operator):
    bl_idname = "render_every_camera.open_output_folder"
    bl_label = "Open Output Folder"

    def execute(self, context):
        folder = bpy.path.abspath(context.scene.render_every_camera.output_folder)
        if not folder:
            self.report({"ERROR"}, "Choose an output folder first")
            return {"CANCELLED"}
        try:
            os.makedirs(folder, exist_ok=True)
            bpy.ops.wm.path_open(filepath=folder)
        except Exception as error:
            self.report({"ERROR"}, f"Could not open output folder: {error}")
            return {"CANCELLED"}
        return {"FINISHED"}


class RENDER_EVERY_CAMERA_OT_cancel(Operator):
    bl_idname = "render_every_camera.cancel"
    bl_label = "Cancel Batch"

    @classmethod
    def poll(cls, context):
        return context.scene.render_every_camera.batch_running

    def execute(self, context):
        context.scene.render_every_camera.cancel_requested = True
        self.report({"INFO"}, "Cancellation requested")
        return {"FINISHED"}


class RENDER_EVERY_CAMERA_OT_render(Operator):
    bl_idname = "render_every_camera.render"
    bl_label = "Camera Batch Render"
    _timer = None

    @classmethod
    def poll(cls, context):
        return not context.scene.render_every_camera.batch_running

    def invoke(self, context, _event):
        return self._start(context)

    def execute(self, context):
        return self._start(context)

    def _start(self, context):
        scene = context.scene
        settings = scene.render_every_camera
        cameras, self.excluded_cameras = camera_selection(
            scene,
            settings.selected_only,
            settings.exclude_underscore,
            settings.selected_collections_only,
        )
        self.tasks, self.invalid_ranges = build_render_tasks(cameras, settings)
        self.rendered_names = []
        self.skipped_existing_names = []

        if not cameras:
            self.report({"WARNING"}, "No matching cameras found")
            return {"CANCELLED"}
        if not self.tasks:
            self._show_report(context, False, None)
            self.report({"WARNING"}, "No cameras have a valid render definition")
            return {"CANCELLED"}

        self.output_folder = bpy.path.abspath(settings.output_folder)
        if not self.output_folder:
            self.report({"ERROR"}, "Choose an output folder first")
            return {"CANCELLED"}
        try:
            os.makedirs(self.output_folder, exist_ok=True)
        except OSError as error:
            self.report({"ERROR"}, f"Could not create output folder: {error}")
            return {"CANCELLED"}

        render = scene.render
        self.original_camera = scene.camera
        self.original_filepath = render.filepath
        self.original_x = render.resolution_x
        self.original_y = render.resolution_y
        self.original_percentage = render.resolution_percentage
        self.original_frame = scene.frame_current
        self.extension = render.file_extension if render.use_file_extension else ""
        self.used_paths = set()
        self.index = 0

        settings.batch_running = True
        settings.cancel_requested = False
        settings.progress = 0
        render.resolution_percentage = 100

        window_manager = context.window_manager
        window_manager.progress_begin(0, len(self.tasks))
        self._timer = window_manager.event_timer_add(0.1, window=context.window)
        window_manager.modal_handler_add(self)
        tag_properties_redraw(context)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        settings = context.scene.render_every_camera
        if event.type == "ESC":
            settings.cancel_requested = True
            return {"RUNNING_MODAL"}
        if event.type != "TIMER":
            return {"PASS_THROUGH"}
        if settings.cancel_requested:
            return self._finish(context, cancelled=True)
        if self.index >= len(self.tasks):
            return self._finish(context)

        try:
            self._process_task(context, self.tasks[self.index])
        except Exception as error:
            return self._finish(context, error=error)

        self.index += 1
        settings.progress = round(100 * self.index / len(self.tasks))
        context.window_manager.progress_update(self.index)
        tag_properties_redraw(context)
        return {"RUNNING_MODAL"}

    def _process_task(self, context, task):
        camera, width, height, timeline_frame, sequence_number = task
        scene = context.scene
        settings = scene.render_every_camera
        render = scene.render

        scene.camera = camera
        render.resolution_x = width
        render.resolution_y = height
        stem = camera_filename(camera.name)

        if timeline_frame is not None:
            scene.frame_set(timeline_frame)
            output_number = (
                sequence_number
                if settings.range_numbers_from_one
                else timeline_frame
            )
            stem = f"{stem}_{frame_filename_number(output_number)}"

        render.filepath, rendered_name = unique_output_path(
            self.output_folder, stem, self.extension, self.used_paths
        )
        final_path = render.filepath + self.extension
        if not settings.overwrite_existing and os.path.exists(final_path):
            self.skipped_existing_names.append(rendered_name)
            return

        detail = f", frame {timeline_frame}" if timeline_frame is not None else ""
        self.report(
            {"INFO"},
            f"Rendering {self.index + 1}/{len(self.tasks)}: "
            f"{camera.name} ({width} x {height}{detail})",
        )
        result = bpy.ops.render.render(write_still=True)
        if "CANCELLED" in result:
            settings.cancel_requested = True
        else:
            self.rendered_names.append(rendered_name)

    def _finish(self, context, cancelled=False, error=None):
        scene = context.scene
        settings = scene.render_every_camera
        render = scene.render
        if self._timer is not None:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None
        context.window_manager.progress_end()

        scene.camera = self.original_camera
        render.filepath = self.original_filepath
        render.resolution_x = self.original_x
        render.resolution_y = self.original_y
        render.resolution_percentage = self.original_percentage
        scene.frame_set(self.original_frame)
        settings.batch_running = False
        settings.cancel_requested = False
        if not cancelled and error is None:
            settings.progress = 100
        tag_properties_redraw(context)

        self._show_report(context, cancelled, error)
        if error is not None:
            self.report({"ERROR"}, f"Rendering stopped: {error}")
            return {"CANCELLED"}
        if cancelled:
            self.report({"WARNING"}, "Render batch cancelled")
            return {"CANCELLED"}
        self.report(
            {"INFO"},
            f"Rendered {len(self.rendered_names)} image(s); "
            f"skipped {len(self.skipped_existing_names)} existing file(s)",
        )
        return {"FINISHED"}

    def _show_report(self, context, cancelled, error):
        def draw_batch_report(menu, _context):
            layout = menu.layout
            if cancelled:
                layout.label(text="Batch cancelled.", icon="CANCEL")
            if error is not None:
                row = layout.row()
                row.alert = True
                row.label(text=f"Error: {error}", icon="ERROR")

            layout.label(text="Rendered images:", icon="CHECKMARK")
            for name in self.rendered_names:
                layout.label(text=name, icon="CHECKMARK")
            if not self.rendered_names:
                layout.label(text="None")

            if self.excluded_cameras:
                layout.separator()
                layout.label(text="Excluded cameras:", icon="LIGHT")
                for camera in self.excluded_cameras:
                    layout.label(text=camera.name, icon="LIGHT")

            if self.invalid_ranges:
                layout.separator()
                warning_header = layout.row()
                warning_header.alert = True
                warning_header.label(text="Invalid range warnings:", icon="ERROR")
                for camera_name, reason in self.invalid_ranges:
                    row = layout.row()
                    row.alert = True
                    row.label(text=f"{camera_name}: {reason}", icon="ERROR")

            if self.skipped_existing_names:
                layout.separator()
                skipped_header = layout.row()
                skipped_header.alert = True
                skipped_header.label(
                    text="Skipped because the file already exists:", icon="ERROR"
                )
                for name in self.skipped_existing_names:
                    row = layout.row()
                    row.alert = True
                    row.label(text=name, icon="ERROR")

        context.window_manager.popup_menu(
            draw_batch_report,
            title="Camera Batch Render - Batch Report",
            icon="INFO",
        )


class RENDER_EVERY_CAMERA_PT_panel(Panel):
    bl_label = "Camera Batch Render"
    bl_idname = "RENDER_EVERY_CAMERA_PT_panel"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "render"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.render_every_camera
        cameras, _excluded = camera_selection(
            context.scene,
            settings.selected_only,
            settings.exclude_underscore,
            settings.selected_collections_only,
        )
        tasks, _invalid_ranges = build_render_tasks(cameras, settings)

        help_row = layout.row()
        help_row.alignment = "RIGHT"
        help_row.operator(
            RENDER_EVERY_CAMERA_OT_quick_help.bl_idname,
            text="Quick Help", icon="QUESTION",
        )

        defaults = layout.row(align=True)
        defaults.prop(settings, "default_width", text="Width")
        defaults.prop(settings, "default_height", text="Height")
        layout.operator(
            RENDER_EVERY_CAMERA_OT_apply_selected_resolution.bl_idname,
            icon="OUTPUT",
        )

        layout.prop(settings, "selected_only")
        layout.prop(settings, "selected_collections_only")
        layout.prop(settings, "exclude_underscore")
        if settings.selected_collections_only:
            box = layout.box()
            box.label(text="Collections to include:")
            for collection in collection_tree(context.scene.collection):
                box.prop(
                    collection, "render_every_camera_selected", text=collection.name
                )

        layout.prop(settings, "range_numbers_from_one")
        layout.prop(settings, "overwrite_existing")
        output_row = layout.row(align=True)
        output_row.prop(settings, "output_folder", text="Output")
        output_row.operator(
            RENDER_EVERY_CAMERA_OT_open_output_folder.bl_idname,
            text="", icon="OUTPUT",
        )

        if settings.batch_running:
            layout.prop(settings, "progress", slider=True)
            layout.operator(RENDER_EVERY_CAMERA_OT_cancel.bl_idname, icon="CANCEL")
        else:
            render_row = layout.row()
            render_row.enabled = bool(tasks and settings.output_folder)
            render_row.operator(
                RENDER_EVERY_CAMERA_OT_render.bl_idname,
                text=f"Images to render: {len(tasks)}",
                icon="RENDER_STILL",
            )


classes = (
    RENDER_EVERY_CAMERA_Settings,
    RENDER_EVERY_CAMERA_OT_quick_help,
    RENDER_EVERY_CAMERA_OT_apply_selected_resolution,
    RENDER_EVERY_CAMERA_OT_open_output_folder,
    RENDER_EVERY_CAMERA_OT_cancel,
    RENDER_EVERY_CAMERA_OT_render,
    RENDER_EVERY_CAMERA_PT_panel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.render_every_camera = PointerProperty(
        type=RENDER_EVERY_CAMERA_Settings
    )
    bpy.types.Collection.render_every_camera_selected = BoolProperty(
        name="Include in Camera Render Batch", default=False,
    )


def unregister():
    del bpy.types.Collection.render_every_camera_selected
    del bpy.types.Scene.render_every_camera
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()







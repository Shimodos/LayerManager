# Changelog

## a0.011

New interface and a pass over reliability.

### Added
- Works in 3ds Max 2025+ (PySide6) as well as 2024 (PySide2); a0.010 imported PySide2 only.
- Nested layers are shown as a tree; "New Child Layer" and "Move to Top Level" in the menu.
- Search box for layers and objects.
- Layer colour swatch, click to change the wire colour.
- Isolate a layer (Alt+click the eye) and Show All Layers.
- Light palette, chosen from the 3ds Max colour scheme.
- Object kind icons (geometry, group, light, camera, shape, helper).
- Ctrl+click adds an object to the selection.
- Typing in the search box or while renaming no longer fires 3ds Max keyboard shortcuts
  (`qtmax.DisableMaxAcceleratorsOnFocus`).
- The window remembers its size and position.
- Tests that run inside 3ds Max, and a script that renders the screenshots.

### Changed
- New layers are created with the "+" button and renamed in place; the separate name field is gone.
- Vector icons instead of emoji glyphs, which depended on the system font.
- Warnings appear in the status line instead of modal message boxes
  (deleting a layer still asks).
- Hide, freeze and group toggles are undoable.
- Script file renamed from `Test_010_01.py` to `layer_manager.py`; the installer removes the old file.
  The macro (category "AD Tools", "LayerMgr") is unchanged, so toolbar buttons keep working.

### Fixed
- Running the script a second time opened a second panel instead of replacing the first.
- Layers hidden, frozen, renamed or made current outside the panel were not picked up.
- Objects renamed, hidden or frozen outside the panel were not picked up.
- A layer could not be renamed if only the letter case changed ("walls" to "Walls").
- A layer with nested layers could not be deleted.
- Deleting any layer switched the current layer to "0", even when it was not the one deleted.
- Every scene change rebuilt rows for all objects of all layers; rows are now built per opened layer.
- The list jumped back to the highlighted layer after each refresh.

## a0.010

The last version before this repository: layers expand to show their objects, object rows
have their own hide / freeze toggles, and a lock column opens and closes groups.

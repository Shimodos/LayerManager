-- Layer Manager a0.012 -- installer
-- 1) Removes older script versions from <userscripts>\python, then copies
--    layer_manager.py there (a directory searched by python.ExecuteFile,
--    per Autodesk docs "Executing Python from MAXScript").
-- 2) Copies the multi-resolution PNG icons into <usericons>\Dark|Light.
-- 3) Defines a macroScript; evaluating the definition (re)writes
--    "AD Tools-LayerManager.mcr" in the usermacros folder, per Autodesk docs
--    "Defining Macro Scripts". Category and name are unchanged, so a button
--    already placed on a toolbar keeps working and now runs the new version.
(
    local srcDir  = getFilenamePath (getThisScriptFilename())
    local srcFile = srcDir + "layer_manager.py"

    local pyDir = (getDir #userScripts) + "\\python"
    if not (doesFileExist pyDir) do makeDir pyDir all:true

    -- Older versions must not stay next to the new one.
    local oldFiles = #("Test_009_01.py", "Test_010_01.py")
    for f in oldFiles do
    (
        local oldPath = pyDir + "\\" + f
        if doesFileExist oldPath do deleteFile oldPath
    )

    local dstFile = pyDir + "\\layer_manager.py"
    if doesFileExist dstFile do deleteFile dstFile

    -- Icons: same file names as before, existing ones are overwritten.
    for theme in #("Dark", "Light") do
    (
        local dstIconDir = (getDir #userIcons) + "\\" + theme
        if not (doesFileExist dstIconDir) do makeDir dstIconDir all:true
        for sz in #(24, 30, 36, 48) do
        (
            local iconFile = "LayerManager_" + (sz as string) + ".png"
            local srcIcon  = srcDir + "icons\\" + theme + "\\" + iconFile
            local dstIcon  = dstIconDir + "\\" + iconFile
            if doesFileExist dstIcon do deleteFile dstIcon
            copyFile srcIcon dstIcon
        )
    )

    if (copyFile srcFile dstFile) then
    (
        macroScript LayerManager
        category:"AD Tools"
        toolTip:"Layer Manager (Python)"
        buttonText:"LayerMgr"
        iconName:"LayerManager"
        (
            python.ExecuteFile ((getDir #userScripts) + "\\python\\layer_manager.py")
        )

        messageBox ("Layer Manager a0.012 installed.\n\n" +
                    "Old versions removed, script copied to:\n" + dstFile + "\n\n" +
                    "If the toolbar button is already placed, it now runs a0.012.\n" +
                    "Otherwise: Customize > Customize User Interface > Toolbars,\n" +
                    "Category: \"AD Tools\", drag \"LayerMgr\" onto a toolbar.") \
                   title:"Layer Manager"
    )
    else
        messageBox ("Install FAILED: could not copy\n" + srcFile + "\nto\n" + dstFile) \
                   title:"Layer Manager"
)

# Replace only the default descriptor translation unit, retaining the pinned
# managed component contents/checksums and its UAC streaming implementation.
idf_component_get_property(eab_tusb_lib espressif__tinyusb COMPONENT_LIB)
idf_component_get_property(eab_uac_dir espressif__usb_device_uac COMPONENT_DIR)
set(eab_descriptor "${CMAKE_CURRENT_LIST_DIR}/mic_only_descriptors.c")
foreach(eab_property SOURCES INTERFACE_SOURCES)
    get_target_property(eab_sources ${eab_tusb_lib} ${eab_property})
    if(eab_sources)
        list(REMOVE_ITEM eab_sources "${eab_uac_dir}/tusb/usb_descriptors.c")
        list(APPEND eab_sources "${eab_descriptor}")
        set_property(TARGET ${eab_tusb_lib} PROPERTY ${eab_property} "${eab_sources}")
    endif()
endforeach()

; Start using subsdk8 0x500 bytes into the .text section
; 1st 0x500 bytes are left to make sure none of the subsdk setup is mangled
; The next 0x1000 bytes are reserved for the landingpad


;;;;;;;;;;;;;;;;;;;;;;;;;;
;; additions begin here ;;
;;;;;;;;;;;;;;;;;;;;;;;;;;
.offset 0x360A6500
; .global test
.global handle_custom_item_get
.type handle_custom_item_get, @function

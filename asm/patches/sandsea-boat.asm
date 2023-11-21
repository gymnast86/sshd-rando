; Prevent sandsea boat softlock
.offset 0x710096f8f4
mov w8, #5
bl additions_jumptable

; Increase boat sprint speed
.offset 0x710096d500
movz w9, #0x3ee8, LSL #16 ; 0.453125
nop

.offset 0x710096d510
nop ; don't multiply by 2

; Increase Base boat speed
; SD uses 1.5 but it isn't as fast in HD for some reason ¯\_(ツ)_/¯
.offset 0x710096a928
movz w8, #0x4000, LSL #16 ; 2.0
nop

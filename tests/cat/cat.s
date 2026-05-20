%define IN_PORT  0xFFFFFF00
%define OUT_PORT 0xFFFFFF04

.code
.org 0x1000
loop:
    mv.b    (IN_PORT), R0   ; move data by input address to R0 register
    cmp.b   #0, R0          ; compare R0 with 0
    beq     done            ; if R0 is 0 then goto done
    mv.b    R0, (OUT_PORT)  ; move data from R0 by output address
    jmp     loop            ; goto loop
done:
    die
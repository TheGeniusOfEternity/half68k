; double_precision – 64-bit addition
%define IN_PORT  0xFFFFFF00
%define OUT_PORT 0xFFFFFF04

.data
a_lo: dw 0x00000001
a_hi: dw 0x00000002
b_lo: dw 0xFFFFFFFF
b_hi: dw 0x00000001
res_lo: dw 0
res_hi: dw 0

.code
.org 0x1000

start:
    mv.l    #a_lo, R0
    mv.l    (R0), R0
    mv.l    #a_hi, R1
    mv.l    (R1), R1
    mv.l    #b_lo, R2
    mv.l    (R2), R2
    mv.l    #b_hi, R3
    mv.l    (R3), R3

    ; R0 = a_lo, R1 = a_hi, R2 = b_lo, R3 = b_hi
    mv.l    R0, R4
    add.l   R2, R4            ; R4 = a_lo + b_lo
    mv.l    R4, R5            ; R5 = low sum
    cmp.l   R2, R4
    bcs     carry_set
    mv.l    #0, R6
    jmp     add_high

carry_set:
    mv.l    #1, R6

add_high:
    mv.l    R1, R4
    add.l   R3, R4
    add.l   R6, R4            ; R4 = a_hi + b_hi + carry
    mv.l    #res_lo, R0
    mv.l    R5, (R0)
    mv.l    #res_hi, R0
    mv.l    R4, (R0)
    die
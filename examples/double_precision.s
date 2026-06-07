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

    ; Print result (res_hi & res_lo)
    mv.l    (res_hi), R0
    jsr     print_64_part
    mv.l    (res_lo), R0
    jsr     print_64_part

    die

print_64_part:
    mv.l    R5, -(SP)
    mv.l    R6, -(SP)
    mv.l    R4, -(SP)

    mv.l    R0, R5            ; R5 – копия числа
    mv.l    #8, R4            ; Счетчик

loop_print:
    mv.l    R5, R6            ; R6 – рабочая копия
    lsr.l   #28, R6
    and.l   #0xF, R6

    cmp.l   #10, R6
    blt     is_digit_p
    add.l   #55, R6
    jmp     print_it_p
is_digit_p:
    add.l   #48, R6
print_it_p:
    mv.b    R6, (OUT_PORT)

    lsl.l   #4, R5
    sub.l   #1, R4
    cmp.l   #0, R4
    bne     loop_print

    mv.l    (SP)+, R4
    mv.l    (SP)+, R6
    mv.l    (SP)+, R5
    rts
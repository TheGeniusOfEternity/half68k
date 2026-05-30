; prob1 – Euler problem 4: largest palindrome product of two 3-digit numbers
%define IN_PORT  0xFFFFFF00
%define OUT_PORT 0xFFFFFF04

.data
max_pal: dw 0
i:       dw 999
j:       dw 999
prod:    dw 0
temp:    dw 0
rev:     dw 0

.code
.org 0x1000

start:
    mv.l    #0, R0
    mv.l    #max_pal, R1
    mv.l    R0, (R1)

loop_i:
    mv.l    #i, R1
    mv.l    (R1), R0
    cmp.l   #99, R0
    ble     print_res

    mv.l    #j, R1
    mv.l    R0, (R1)

loop_j:
    mv.l    #j, R1
    mv.l    (R1), R0
    cmp.l   #99, R0
    ble     next_i

    mv.l    #i, R1
    mv.l    (R1), R2
    mv.l    #j, R1
    mv.l    (R1), R3
    mv.l    R2, R0
    mul.l   R3, R0
    mv.l    #prod, R1
    mv.l    R0, (R1)

    mv.l    #max_pal, R1
    mv.l    (R1), R2
    cmp.l   R2, R0
    ble     next_j

    jsr     check_pal
    cmp.l   #0, R0
    beq     next_j

    mv.l    #prod, R1
    mv.l    (R1), R0
    mv.l    #max_pal, R1
    mv.l    R0, (R1)

next_j:
    mv.l    #j, R1
    mv.l    (R1), R0
    sub.l   #1, R0
    mv.l    #j, R1
    mv.l    R0, (R1)
    jmp     loop_j

next_i:
    mv.l    #i, R1
    mv.l    (R1), R0
    sub.l   #1, R0
    mv.l    #i, R1
    mv.l    R0, (R1)
    jmp     loop_i

print_res:
    die

check_pal:
    mv.l    #0, R2
    mv.l    #rev, R1
    mv.l    R2, (R1)
    mv.l    #prod, R1
    mv.l    (R1), R0
    mv.l    #temp, R1
    mv.l    R0, (R1)

pal_loop:
    mv.l    #temp, R1
    mv.l    (R1), R0
    cmp.l   #0, R0
    beq     pal_end

    mv.l    #temp, R1
    mv.l    (R1), R2
    mv.l    #10, R3
    mv.l    R2, R0
    div.l   R3, R0
    mv.l    R0, R4
    mul.l   R3, R0
    sub.l   R0, R2
    mv.l    #rev, R1
    mv.l    (R1), R0
    mul.l   #10, R0
    add.l   R2, R0
    mv.l    #rev, R1
    mv.l    R0, (R1)
    mv.l    #temp, R1
    mv.l    R4, (R1)
    jmp     pal_loop

pal_end:
    mv.l    #prod, R1
    mv.l    (R1), R0
    mv.l    #rev, R1
    mv.l    (R1), R2
    cmp.l   R2, R0
    beq     is_palindrome
    mv.l    #0, R0
    rts
is_palindrome:
    mv.l    #1, R0
    rts
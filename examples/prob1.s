; Euler 4 Problem
%define IN_PORT  0xFFFFFF00
%define OUT_PORT 0xFFFFFF04

.data
max_pal: dw 0
prod:    dw 0
dec_buf: dw 0,0,0,0,0,0,0,0,0,0

.code
.org 0x1000

start:
    mv.l    #0, R2            ; R2 = max_pal = 0
    mv.l    #999, R0          ; R0 = i = 999

loop_i:
    cmp.l   #99, R0
    ble     print_res

    ; optimization - if i * i <= max_pal then there won't be big palindromes
    mv.l    R0, R3
    mul.l   R0, R3            ; R3 = i * i
    cmp.l   R2, R3            ; compare R2 (max_pal) and R3 (i*i)
    ble     print_res         ; exit

    mv.l    R0, R1            ; R1 = j = i (skip duplicates)

loop_j:
    cmp.l   #99, R1
    ble     next_i            ; if j <= 99 then goto next i

    mv.l    R0, R3
    mul.l   R1, R3            ; R3 = prod = i * j

    ; if prod <= max_pal the stop j decreasing
    cmp.l   R2, R3
    ble     next_i

    ; potential maximumn
    mv.l    #prod, R4
    mv.l    R3, (R4)

    ; pheck if palindrome
    jsr     check_pal
    cmp.l   #0, R6
    beq     next_j

    mv.l    R3, R2            ; update max_pal

next_j:
    sub.l   #1, R1            ; j--
    jmp     loop_j

next_i:
    sub.l   #1, R0            ; i--
    jmp     loop_i

print_res:
    mv.l    #max_pal, R4
    mv.l    R2, (R4)          ; save final result

    mv.l    R2, R0            ; print max_pal
    jsr     print_dec         ; call decimal num print
    die

; print decimal num procedure
print_dec:
    mv.l    #dec_buf, R4      ; buffer start pointer
    mv.l    #0, R5            ; digits counter

pd_loop:
    ; find num % 10
    mv.l    R0, R6
    div.l   #10, R0
    mv.l    R0, R3
    mul.l   #10, R3
    sub.l   R3, R6
    add.l   #48, R6

    mv.l    R6, (R4)
    add.l   #4, R4
    add.l   #1, R5

    cmp.l   #0, R0            ; if num is not 0 continue
    bne     pd_loop

pd_print:
    ; print digits in reverse order
    sub.l   #4, R4
    mv.l    (R4), R6
    mv.b    R6, (OUT_PORT)
    sub.l   #1, R5
    cmp.l   #0, R5
    bne     pd_print

    rts

; check palindrome procedure
check_pal:
    mv.l    #prod, R4
    mv.l    (R4), R3          ; R3 = temp = prod
    mv.l    #0, R5            ; R5 = rev = 0

pal_loop:
    cmp.l   #0, R3
    beq     pal_end

    ; rem = temp % 10
    mv.l    R3, R6
    div.l   #10, R3
    mv.l    R3, R4
    mul.l   #10, R4
    sub.l   R4, R6

    ; create reversed num - rev = rev * 10 + rem
    mul.l   #10, R5
    add.l   R6, R5

    jmp     pal_loop

pal_end:
    mv.l    #prod, R4
    mv.l    (R4), R3
    cmp.l   R5, R3
    beq     is_pal
    mv.l    #0, R6
    rts
is_pal:
    mv.l    #1, R6
    rts
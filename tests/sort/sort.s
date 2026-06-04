; sort – load 5 numbers, bubble sort, output
%define IN_PORT  0xFFFFFF00
%define OUT_PORT 0xFFFFFF04

.data
array:  dw 0,0,0,0,0
size:   dw 0

.code
.org 0x1000

start:
    mv.l    #array, R1
    mv.l    #0, R2            ; nums counter
read_loop:
    mv.b    (IN_PORT), R0
    cmp.b   #0x20, R0
    beq     read_loop
    cmp.b   #0x0A, R0
    beq     read_loop
    cmp.b   #0, R0
    beq     end_input
    sub.b   #0x30, R0
    mv.l    R0, (R1)+
    add.l   #1, R2
    cmp.l   #5, R2
    blt     read_loop

end_input:
    mv.l    #size, R3         ; size address
    mv.l    R2, (R3)          ; save amount

    cmp.l   #1, R2
    ble     print_array

    mv.l    #0, R4            ; i
outer_loop:
    mv.l    #0, R5            ; j
    mv.l    R2, R6
    sub.l   R4, R6
    sub.l   #1, R6            ; size - i - 1
inner_loop:
    cmp.l   R6, R5
    bge     next_outer

    mv.l    #array, R1
    mv.l    R5, R3
    mul.l   #4, R3
    add.l   R3, R1

    mv.l    (R1), R0          ; a[j]
    mv.l    4(R1), R3         ; a[j+1]

    cmp.l   R3, R0
    ble     no_swap

    mv.l    R3, (R1)
    mv.l    R0, 4(R1)
no_swap:
    add.l   #1, R5
    jmp     inner_loop
next_outer:
    add.l   #1, R4
    cmp.l   R2, R4
    blt     outer_loop

print_array:
    mv.l    #array, R1
    mv.l    (size), R2       ; load size value
print_loop:
    cmp.l   #0, R2
    beq     done

    mv.l    (R1)+, R0
    add.l   #0x30, R0
    mv.b    R0, (OUT_PORT)

    sub.l   #1, R2
    cmp.l   #0, R2
    beq     done

    mv.b    #0x20, R0
    mv.b    R0, (OUT_PORT)
    jmp     print_loop
done:
    die
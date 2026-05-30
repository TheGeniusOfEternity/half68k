; Hello World – prints "Hello, World!" then stops
%define IN_PORT  0xFFFFFF00
%define OUT_PORT 0xFFFFFF04

.data
msg:    pstr "Hello, World!"

.code
.org 0x1000
start:
    mv.l    #msg, R0         ; R0 = string address
    mv.b    (R0)+, R1        ; R1 = length, R0 points to the first symbol
    mv.l    R1, R2           ; set R2 as amount of remaining symbols
loop:
    cmp.b   #0, R2           ; compare R2 with 0
    beq     done             ; if R2 is 0 then goto done
    mv.b    (R0)+, R1        ; load current symbol
    mv.b    R1, (OUT_PORT)   ; output
    sub.b   #1, R2           ; decrement R2
    jmp     loop
done:
    die                      ; stop the program
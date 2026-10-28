#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline, self-contained V4.0.6 Publisher Category Hotfix V2 installer.

Copy THIS file beside run_ui.py, then run:
    python apply_category_hotfix_v2.py
This script modifies ONLY phase4/publisher.py, after creating a backup.
It does not access WordPress or change Duplicate Guard state or metadata.
"""
from __future__ import annotations

import base64
from datetime import datetime
import hashlib
import os
from pathlib import Path
import shutil
import sys
import zlib

BASE_SHA = "d04c673aecd7f045fe7bb9e1413f1f67b48d9d5891ecf3679b1c21fab08ca4fd"
V1_SHA = "4db52945df4dea429ae96bdc9a9e79bc5d8aae4e84d501c61ca70435d8b532e3"
V2_SHA = "ba53660682da97b6149b16c1fb2de84c54112d50939d4a894a1a242f96d5534e"
PAYLOAD = (
    'c-rlK%W@<~a^M|b5zJmrRSgRXbT`SFK~Hf60)-|-'
    'Gyub+Iouv7Em4&P<e)0En3>gR3<xu6ZFi&tkNSeWP#Rm)tR8D?d(n5Ghc|u6`XiqCC=}35=^`H3sEi1Y2oDbrcMo@uM<1-'
    'r@@(ZaPFAAiwU}NN=V|hE>5*9e>9QE4!#Fux6SHEp{B!)WwB&i-'
    '(oy(2yhz8QKaK`PmL~Ba7ytH`e=D|=B09^$A{vU9AB+9-FpmWMJ3Af6`FWHr^&a-'
    '$($Yqn6j?YZ)|Qq9{GHDxQ7+PCd?mu^G)rGYhZ|vn0}03C^I0++L-{C6CnAf&;Z-'
    'n7vtTwIr{Qqrm;1Y)t@sEBiVCRqRhn+3lSz~fBC&a}zIAj+ke`XT5J~hp%EVwC4=!>w4{W=irNh~vSk9-'
    '>ARfg7G0mdUI6gZsR`Md6icuJkXBhw=rXooT5uT=5A!bPyjR`wbZl4pZC|j1lMP5L$h;#TO&7fYKh-'
    '{V=@gxeUXl1H!N%Qc3o2LoFxJ<Jl3?a`02`Pw&VnyU3Vupc2@#`olU`T)nz!QDqUI&PY7$GekMBmI}>{)gMt1m|5^m1+KaY'
    'xNs#FOwW5)z-II02mJ5t0JHcqZ0&jzmvHZ(zA}4@F#zqpp}l!#Lz0P-'
    'TC2>4^c#Uq2F)5GMV_(Tkm>rya2w79q?wDr9fs@;pjtLbJR#NGH>A1n7JwcK42gt-'
    'a&j&0u41cWe9LMSl~q_&OZN!<8hJt(QLTi1nh#;?o%{{F>MgVNrHxlhY{cAv&Lla5xli|MgFQ|HF5;|BLC1Ivi-'
    ')nudc5oIC&rbf;s$@6sn7AU+`cG`qs@1E$X*(_e8OS<PWrWYJli7unUyDUqqa^l3*No+Eh-qkNFXQ^X=*$258o6`|NPh5pj'
    'dI^rNqF2swlI2VWgJ#i$FSFQ@526AZ2;boY?nn&3Lu##N(OFy@vjMBj@7Z=eLl9FD({at_Q7cf4cBe9u<qk@nEbg~OXJptx'
    '0ilgBgEOR`7<prW0T!?RGAy8~_)fH#qcpPQ$ha@JZL|+_!c}z48%UYyXPwP87dtU{I+eiK2s{{DIn9TA5%8_1Sf>+`+5=Az'
    'PV6Yi%+ibXxBoDO;B45}|$efl4??Et{6|e<^0LXQU=nWItiCl4MNq)oqqyA2F^;Z_Dzw#^n5jUa!8+cK43Z%e&4S`Ar<1o)'
    '*!^;}_Q&)ufFdh`TW`uyOYV?~+r?3#?_*50{!%x_edqCTp+XuK|;6ocG7LQ?C9bXb)yW>w`WnpW-dVI1Jj{wVATea#C`+*$'
    '=Gw~7r+LD0()Gt3y@+d3Xt6jHMhX+(#O_2e}@vJAXlzT*1;g~DTvM~%8`_J{9;2ZshWygPlZvY4IElS`piR9{><{zu-'
    'pGV=Wh)1*WVLF>iETsh=MY00!+<-qxG>yZn%M6*VpI;?|Ae_cRuNV9_<y}D884P46g<X(lUDzj+D4iAkECUJ(fu-'
    'xJc8MJ109dd;fgOd58N7a~7Y%q$Hi;A1#_>QiT*=~Q#UM#9EdXl&1u-3turV}2=7{@%`9PrSA^!l-fUhe#Upz-Y_BHDd<S8'
    'MkM14NQuZMVUbR`~4gV|&f0_Y+Q)O;+^PlFNcz#w`<M=Ua!Nt%zMBEZv4Q?#TuI!fi7mzGdWcz^!^w3koCFwO^XqG!3q0uT'
    'D@n_r7ld9V+!l5m3G@stMcejaASWuz{BunGV%1>X98hxh)c3$n~8KAUC4mfrVh4>u0B_ZQ?HOV%#aYycz(&xa3QXKCrH{a|'
    'PB`Sxybe6R!H(%e6bsIq65cwOP07sWJRTUjYsNQ|_M=)-'
    '}%GEUFpWO)kP((CxZbK+^cgTRju`v<%0FZvbOssKT|P4?Fh55L+w*sL^B1>9t5=?kEqo&MpWTTy+*TBC5BTLbbz;)$|$2N~'
    'zJ_ZVy7xr6^+MLGVHCf-f;ymH`|OCR3P661G&{W*YI-#!Xn;8cL0w5{%{b+G-'
    '@)zwuG*!l5xb4yc(Eq=ibcJ?;bkM<6NqwN>{z2l}X%XJXI&sCTEJA3P!a{*MUVEa#3C4i-'
    'a<6SHYkRBBYTdnP4Uh0ky!a|q~XE|eaB$}#sL<B1#6s04ERX0wrumgZ%a}WPuKJ4MJf^DQab$a{2@!PbhBmCL+KK%N_$%n('
    '>!!JI3@!=s*AhzIbsQXzF3`UjtlZ#=TwdG0PI|4H3g6IPWL6Bb1&(4p)e_jC79Ov(w@%)*VewOI}O2%i!j3tn1vW6lD{Y^)'
    'w`6*@WH7#qrf|3&|Ixi;UfW#P<j?_2PI7d-'
    'Bute#=EhpWj3}UF%3|XK%#u_K3Dy)52!<7O6%93Tk`cMbK+O*JLd9`Z_2Iuj3*w`RI`2#e(HQY~bg-S_2o}F3PiPE5iZ4?M'
    '>d|4%y6ky>5rCD5&E((MvCqUG@X%bP3a0p^ipj7fTahj%MC`an0a!`LG*h2xF+`#xs6`JYhV3r(2`D|QNNvFIRb&7C_kn91'
    'Q>Y$kx0f?z{Dn}?AHk7~rt+|t)ouTl(!dlb&-'
    'lM~41d{bxdjgZE%?7jSh~>{{I%^8Ilj&SG_r=<WFV={|VSUglQLP_&*VOVxd@HUc_#01d6+8g2URR99v;15#Hd=}pw9vNVl'
    '*n$C_zI`w8Jw9Q&?Rjz1Wr$?1mLFUkzERyIf(Kj9yI<p@<FCABI*b<VDC2xN&z(GK{zF?a2TD=&e~I&IqL|Ls=5MXOGXFG#'
    'p@p&>>YR|#3<4NhRx@N9P%_N7cauqi34U=X81TNANFGuCBV&!Hu97ns%Lh;D~M+t>Wx2506l=v*%*1_S!BVD-VCB?A^P+WZ'
    'f>g+*kzTjo4P<A3QIs}1s?OJAk=|C2RaR`Xs2dP7U};-'
    '5U5L5K;VPZSwY6hmrwoGA7dAxg^`$l+c1A37?)A5Rk4li4hV>hcqo781i>eOgyafR9jqS1MB)72jPU=YxIP^8avq;4@E|sk'
    '(IAf#*vQEsY9q8R&8K6!$if&TsF&e*#+|o;TCkHF(BDBxLl8(GXwD18pC9h+iuClipbJRS$RgN?2@O>4%~71ezK}<J7M^9{'
    '^t`Q4Z$c^jD|u5oL)PRN52!9FAd@khBr@3-'
    'R>c<nC{BiLZ|doZPSFsBJ6og~4S9<4BBRI?9+^erDetH`Q}+zrDGd}&n01(dddtydT3m@=PCs*TL3`Y&IE<Ck8HfVXNYIwH'
    '0@$4voz+NJp6BhLxfCY`Ds_2R_%LNLj?Titm9j5`#vCRIS$lFJ&u0P5H}cV@hA>UvN)|U?EQPXOCW0nbd*tq1gDlvdO?H*0'
    'KJm-EUBUkr=(4+Mv6TW~MS+!dpbo?&&U3oRxHhA>@tm>32(6u59)u<siw`5Ew7r46nh4Nj0W1y<3m_#>M#Kkjethh&dh_V!'
    'ILT*Iw66fRjk$vdDaxRqq5W8vWztZuCV?j7%Gh8N6hT4;ZapkbUN+7XEHtR`k?Z>d5Y<NMc-'
    'W??OcU$FVp~BD6#&Av2kCUh8V@eXBrFE!YA<T*SZ@Ktn3`tCm3~jhXn^hscY$OnW8nIxBAByY%DwyWTk=>Cdtp@qbz5PoxJ'
    '5>Tsa*lvI@q`d-28)Hsn@x@*1b0&OZjQU#`N)(xOO3Zklj2JXRy-'
    'O>ZhU`d7n{BJXBN}H2%~wv8*JOqB&q>4TjeC)a8jsOjr(rRB{h*$z);2SV|1-Y1Uop8g`q38YV-gY^h5w#=0GdJp~QuxUes'
    'Nh<i)?g)`6_$`nT*9deV3Pr0J}>{NxBQG2eTv4+fKeSiO8?`40}!|GNgQkL)<lFW#*^49k5`p))$m9=G0a(v9*p<>LZ6CQ8'
    '#P^4rju5De&C{=Go!bf(*`-'
    '>&R%3kEp&V;p2Up^y{lw<>LO*PSiDQQxHX6e*sXd31{4v(6%1Hs^|<?$i=pszivk2wNcc~FX;A0SJVD31*tax4{8)tf=)9s'
    '&m7VuM4&!Af4axpdHFOfF?gppP!$Ys*X>Ay6qdwJ5+vuz{eL9cx*iaXXO;8|3ltBJs<fSbYd#$SIkruBeq^TTxz~t+pOHGa'
    'lwH-'
    'yG(pO;1D~B|}4d&;+NCT6u0`qsEL?heg?(Orr`Eab3;OxxnJ7`j*|2W3ZCjS4oO?OP$py70q3dxvOG)1IqpY#ITJtwZFMl-'
    'NezjGE*3MFv1Q{(g0;-;>@{%Tw@mk1kOFG-'
    'H~cODh(XrDVpQ1^;r0DcFj{|deQ~8LJic`73Ro5Y?V;lL)OrOqh`}(c0snu+E!Fj-'
    '^evw%A0_OL6)qX46tr|ZjDuGN?E9jIk4-1Dmj@kCW)Mlv<vY{<E)_9XaZ-aRJY<pk*?zHQCePc_~a}e+I8h3K#|0X^6jW!1'
    '8w{*x6=jn?aCJ7a`STe{8I+UEfHu2BtKMa(F-9Llp^$j8O6~UI4?T6I0&^hY)4gY8)H<`n<iZrrF-'
    '%sUkZFZ`ES>p_dWd=f27}C4Xpm??V01XYn@0v^Jlk#)%4t--O5!&PqPjKqN2d|Dqp&e64bMQbjvpmJ^rU#x}oUN|4pwAJGk'
    'fm>{hNTdb$M3qlf?N8tUljzq%C)>6Jg2!PwUqJy$2Oi<nw#yc^o~MIhRTU4(Ty+?BG^D7S@xJr1R>LYpi!#SDnix;Syj@T6'
    ';53h_=snhFU{&3$CqqtP?97d1D_!L5m=Awjp2&(NiZQ&V1h$Z~YWLcI($dh{|POGdjrrSDVnU!;M>u);Vrl02q<oCo|%>uG'
    'Fq05Z;s9Ipb}o)79@7d_H?<8X3148?R!RWr(<B}hA_RWnNxgDevo54KZNGk+yr@}|j&7M`4XcwqvX_d$PaXZ!gVM`G_wyyM'
    'WV@W!KT#OYmghf3kDvx?*O1$=Wy&xn7;t!dgPe7RCwO`|qc@AyH0pM&6L4fXwjykuz_Ea;A##~Vk2t~7Am7HGPwsp;{?HBd'
    '@Cb>-kB<)4ky(-'
    '0V<a)EsZn)f_!54|qQ%a7q2Us`sem0rcqv@EX6vxt00r^cUF+b$Uw2h!A;rD*{uvp3d_t4Y{JjVh!Br=&a^x-'
    'tAx<A%<D#2pUvDEpr{;yVt_ap{pKu<eOsJ}HNqI?3F@f@cXjSu}((#^E?;ryqgcR8D7W`zf+Q<)(p|N<@%D8n7Te950(CD6'
    '_3euZpfyLjKdZEZ!QsIa>JcSXId`0(wXh1$5H|)yqh<0n^ZwCpXjuVZM+y@!SThPF}r10-h%{;Xk-'
    '8^Hb*rR5f5LxpV(UH#@`GWSX}bA9w|q<JD%E58}ADg`P$rX(YG^y(f(~bd5Xvec#L(S4(jojbW4KKgMO;Wf&L1BzJChC${$'
    'jC<W@$zI>~T1_o-'
    '6JFj4W(Do$9?SlX3{Y+Xesm#W0s^eT>y^ix3R61t}>>f`CDN+f!4s?a=BbYlt>AT8f90JYBYj(Pkr+fI0_(-'
    '(d1{iMKs%usUDC+U*>Z&hQnsJy*LexGCq;j64O~3~JOWmt=!w#*~oao%w^K&>v<w#~;JV50Ju|4LwwN>*@rSbsuaop-'
    'q)2F}N)jBwsm_&^*Ig8qpIB8SWF3i^!5bXb8A5A3K1cZ&aQ(tRD6;WJKtJ(n1+Dh2MJ;@h2?kh_IHC&H?3TZz6WL0T5RZeV'
    '{%G*ta9KDbT7i8w}#ZgA?``3E;ZhWy5qR&0Mx?GzPN#R2KQH;|(3Mif<n508E{^L<V9vX)1OZy9#DKN|Q@jTIu%=;FBcs_N'
    'tOkJ(X*#JY7B!T9e)ha%DK^n!b(rLz(=ZKR9YQF9suXKr{?pD6Os->CQNulkkKo@LNv`onMy7vIGaPt;-'
    '_bSYw`Zzp|#y#)$?{5G3_787=@0}=kt;HK}P-pX6o>V^>-'
    'qm~Z$?B?Gp;KN3pW?9;!|S1ot6RrD1iIqsC##(WX`q&05g~#aa+-'
    '$O&?jS3+w13pa2k14wlSygyZfgJf?RR2wDf>oFjqeHHqzOcbuFR?JAQ_uvIwa5lfpoN*J^{4(>OWOly|ptIB6~d+r&_OtAR'
    'k%H*vI_pT`q+(RqbxO^>bFCl=MzH*aimvb5mww9qLOkL-g-'
    'd{$;MkC<Cd$1*yNosB?JIE#`f!}tV>|6*hcIaz~wzlH%(hsbuD7`wO5(8}vawtOA{E;4a=T25L|UPvA$Gj!v|Wv!><+o)Bt'
    '10LC6mXY~WEkbz&5(#{OA@nX?W+qo!4RiLF7WVI^ap5!UW!c90X*PnrZd|jvH7rcaD#X$KIDr*ooVa$&1zhMPJn0Ck#ZWw}'
    '8SkVjI0B)*p2ua=9*3?-7?b2v@sTebs|vSYL6-'
    'sv#kMw&FiPnhR8hG$Xl?=h8U7VvQG|o@2`(rTKHcJ?ipk99a5fkqh&(<6g3vo>SuQrWk*Ae7jX<S?ZeS{~62q=o-'
    '`&&=q8K(oR_c@D|F~PRcVLw)52FG!dfS{U7g!E#J-N~(=#U)Q2QXfVMp#4`sAyxTQFyjQXC)&W5t*-'
    'SdIBR07Z;FWM9^m5t}9dPow{{Z?)4gWAX-E){uFNuDuhPHqAV*Ji#m4-'
    'K8x&9{>U`3%*$J|J6Yw&I)So)(5Y^?EYT@`lY27{Bw@9!ahfA1!W%o*6P!^lEhsD*;`0^2uJ9hvnn^b=p;jv{&SzOyiIOn('
    'dTFwGHqB#tRM}4Xa&eh157O~$k}R`xk*r)d(|baGI5<AX@j?U0r6|xk(IRjyEkRbnbs9B6Ae|<vmK)8XJEXF9iG+~)@Rr(L'
    'olc{2u~bpu6vL?7uy*&oYx~ztR}*vZ+8xtP9ZpAHX^6e+(uc|pzn4DhOl9OL#Zf7SY;L|oL4C5Ig8G7(mvuN?hHPvh%&h2h'
    'qJg3L7J5b=Nn|u|rN7dTiv9{Jggl)YegM>fj+XK0Dj*4Y*w$ttd1||kf$qt@<mxf%^adRr^_hk<djm&7A|hu|DD!g;$5n@H'
    '+xycWZ~y6s@816Y_FsJ8r<k<c@8Q=UZvWx-``f=$E@?p3(mRwu(~iSHdzzImj_HuVtLJcx#w>K**gK-'
    'M1@SP#+z&Y){qE`6DALpjGji4EYRs;t>}tplI9|F-_f)O#0%NJEmU@cP!K%LavyAC@TG{8+TxD#@-'
    'N{?D__kbStvV$GiN|BKi4*LmZD2NmL4QeArqRpNYRHLR;n6IiA-Lo8(9ZIi7^Z_69d_T$qU`EW>P+k7al2MkYju1W-'
    'x+$$ppmAuPHJEV!`&s9Vciu$Qq{RX)l+<*`tw3dM%adhvh{4U1s7R2b(K6t*XZCi`a1-ix1}v-'
    'v8I&nDo;7e;<Gc5w6RN>?8QoMvvLrHn6jq0Qm*Cc7_*g3CY0!87@?<`fc>F%JdT&Z&^04!u5FJFYz(#?oTC*F|2iGdGH;$S'
    'PY&GI(;}d41A0;OjEou53YI)S)t=*@YbM*n{gtVEs|br}19kRI$&75%GK;<XdkrsnkY!WrscOgh`8bNE?N$Ftr_svrqDIS8'
    'gw5KXQuahRDuC$ZRi&a~5a%eS64(j)ytv9Qe~*V!>2+g#s>kGE1bwE!LXP6(>cvK1v}0wVk~j+o7kHqdas>)w$S2p)d7N{i'
    '9+}e!#vRUJrjL|&GPZq$$jbnGsA-<Z!(o&lslSZ#8Se0O7`f+QdZE;e2)8GQ7KS%Ko%So9-'
    'S&{@bwW(@+T9QlI*;N0K{qwZ3Gl3Jhb%RbMAN>ElVN%Zw3b{=29fy5PlWuF99vY^olZ@2Uj3TNp!5_QGLjF6+<A77ws5*f?'
    'H13b)zH$+74P+{b#9z5H|S<FI2UbL-'
    '0K@xz(ygZ5D~gO>vIUk(;r9p=jT`3Lo>8z<sH|K#&vj!#y;^`>C*kIu7YA+ed1h6bSe0+7V*PY7o9*(PsybQr+Cxp+z*Vz-'
    '$HQaVe_WW&Lta|nm0hFmguFoqoi0R-dNI2dU1#IL!V$6%j24ObgkjuXs$qx0L@oKHI51MjoOY2L&-'
    'tj08<_fcf!)H4~?Lzo)8V7baE04l;w&-qZZ!^yfQ=1b#2eY1m~d3ds?JzyR^%PADQ}k-'
    'Y}g=ZiehP8hZNJql*!F{oqPS)l?yJY?wEL&iV&Q?Je6XkF2=y8px@MUOVIFs*i9`0TE736^B^ypp)s#-'
    'gWp2)LrAkdUp*gpPf!9Na$S$#ekZJB(LKZtNiG4y3BRvjo%>)VD=#9Tl>UCyDnC=U#Dqsmu0==6HTd7l&Me5WxzZVTWK~yZ'
    '#&Rp*_v}2N#JNIV7ZLtaU}knq}e2V9iPcmhgCJ={u+@dbs~~*5$bssjr=$njAz3rZ?{$e$CMLerPUGNep~N3P_Iz6TaTzEl'
    '+0Qf(bW^l479*|L%Ez1oYOF~z&Hnht%yDOWYxZZeW(uh_=&BAc?J)j%11}|on>Q^!CWoPOuX@iznaDY6cJ_;sFE;)+gjh=>'
    '2F$w=h~BNhkVnNXbYqSqK6u;FE-'
    '?z7oJ4oS`GT9j+wJFs8fZnQinsGj06hWZXi3wsUycyY4aRj@Azm@d_C6o^TBz9mi(0!^(Bdb{|{~qqNizIEQ5sMPtT{n!XE'
    '*#1vwB;pU3FZ9FPMc9791ReTpNuvy<4G>&j_4dm8uPZ(S)KG|%BOX_<DiRT?NL3SkB)KaF6YMKTpB+NN~)17rFH%1wB~RLv'
    '`j_ecEs@XO<_%-K4c{qA>H68LgP*<-|nVesBREYd0FkhSum%5tC+y09wFk-KE4agl{t41*t>r)gdqoUIxlIrkjt#m@mY$ah'
    'xSvsUNT>WQE66=Mq-!$-'
    'nm6eu*&nzi7&PMg@iZs|2_t+izDt!^uCtr_>@veW?09butW78Y8TuwYnl)s3wyUbP<K0P<zv@u2OQBLfZ+K-'
    'MyPwds$JYn#p76@q)>6<^e6>1E{x*Z>5M{3;&)1)Ro6%-'
    '%_>qwNy$@QraLLMVz+*jAkM5`+4&kbJy`Z#tG5%yBSKYB~;m_{rB9E$4cUKFx79LZrsY%s7k7t8yJ~!vOBMX{O`xViu5k;|'
    '$D~7dKF94NP?cUoj+yTF&W%vKMeAH52k<Y_;sEIwQAJ0Q8hcyk9B8h;Dl@$kMIf^-'
    '!FA0woj2gpx7%ynEYO>o=!F0qx%mKkEGE6o?M7gLyhamCYA4v0;lw(rR_eir=JaKvAq9oTAmM-JbYo8Kw|<-'
    '03=tRq6!KcioNF4PcYDB|yBsd^}%QYP|qn6i*!o3gtztg&6{8hZex;BfIz@yJ<P+g8U9_g(j;Qr4H+4R*#xS00%-'
    'XXP3#3O6u5rC%=xx^D1YYIUQTq92l{;-`~|S2wQsxFYvU)gR<3>0_k0N*urAut`-'
    'SNm?RH=s7HoRPX26G2|Xu(sQHp4<m}SOjVAt5lj9;VGiE1qxW}ByqIEVd?!~5^+t_AS?8<AOkhu2VeZKpASesPhm>m5_@%x'
    'rO7CPx0M%67SyI3CJiLls{CE!UCK0NC0i^uRsT_SWiu1l%Vm5^AwP~M|FDwc_@73Z_bX#z^HzLGfUNCj!mO4nazl-'
    '9fHzGsdXYt@6b>b=@>om4?mUq-LzHP|4_oI2_D?{2@p{l`E3@%De?zdw8@-u~<DKfe8&x4*yr<J-Ufx4-'
    '=E?O)%1?{(&QiQe7Cv2=C;MK7NZN&*1}kA~{-eGT)ZR)s>mKXsKTXEEnEi7ujNkv%}=0GQ{c*(p^=D{o+a=536Gk;HC-'
    'P&=I}*>AsCf8G~cpiGIw{_c?#@@CqZkoD$k;z}dmx+^BO#p8S6o$-B~Udq?Sce=HBwFWH5amC{h>XT-'
    '3N{LD;mr=ISC>$3*CN=;(ZGrnB<c>Bib^B663p9HlNLk|Z+Pnn9zxlNZ6;S3XhO!D@WgSUTTs}8oo_=uA%|<L+(v`V2YVTx'
    'qvnmxcplLF%xmCS$w;9EZk+(5{vgG>@TnT-?iF%ukF2vqIJBFV|f*fFCx+^1nyn3YBD$!lTnI?-2Vq&e&JqM$R;$Zt|dt-'
    'e^ynO6`0-WmCYqD<nf}YZ3!TQh0H~Umt2&17d<=q9Gf)?OqkHkxAVmsnSAsVcP%PcamV-'
    ';VVvU31Im!=642snpD$ubsbS%ETC=*5r?93fN1Z|Xv&8rCe<;;s)~t?VQHjE7xHy<(>Aj8|WUJS+LLaWWw7^+iiJzS911e#'
    'Nr|-?E9L%PM}VG8K&TOegxIR-EGn+ER#QjqbtKB)Zgj)}|%vd7AfWk^B=U{-'
    'oTA&VAf`xIc2zgCv55{u1uw7C_eyHG8_+o`#s1Zs=Rk)~y_ql?9-9gjsQ(W-'
    '&g7f?)~L(R+ZwrI~9RFHJ_F#&XqNa&tFY_3c=Tv$Fq;BU<bq^j~iGzY?4Mo%OH#n=3E24-dC@pF_D<YG%)-'
    'cRi1?Zz`=lX{A9uM0o-bHjLllws|$ELUX9u)lW}-'
    '2L6n0pDz8l1_U|`Yty5Yx<FWD8Ml5n^7mRC*Wmf9^@Cl;t0E!b|GjIgj}Nj2XH(_2)VsEa@Iiwcxigru`b2i}hc4vEa~8o2'
    'o_=Cono?<y@Y#BL3K}IJlmi-3I_5JCSw1Eb2vm0CA4QFPVyThN(^oo0-jb79vO$S-'
    'h18RdX;UZ2$S|#{XHHk>)O`AEBUg|{TS3#Tcy$@gWl~YNmdd)$WAi>ROdeJAp`0G4F}Ig=w<<NV)0w#}%$@2}o~p_1Rr3bf'
    'Gj%@F8*o#)XK-U7EJv=o8PpG^PLwj^a6F!_s##@EDMF00qABor<-;`BG}mvdPq8)HJJ1;TVAtOkYY!+*^{ljcCnB^9po=*-'
    '+u>leOy=C+({S|{pA0@-9Y#M3SMLEL^bv-1D74H4-@pB<+kbldH@AO$`+LV!&}buQy(0|Akw7B$KW#(*X&d_Yvkke-sLnow'
    'oTSb=<hHzrg{YJw($TDHR6WU$lpL$F)F$cd?EIPZ0V%Pnhw6LHBLjX>qp>w|Gs}L&g&=XN`%Q9g9hKF&`RspvW6R`)D~Yre'
    'Nolkz6&OsT))jg1vfnwHqAl(_t?!{inxg~<#mgtNcGl^CYXWCi5!2bLt}Lc&-'
    'COzBV?Msi1W!VOLMnHO4ph|ub0;pmg!Xp@L9Zco8c1I{Pbau{daA}9IIY~ebMB676-'
    'm(X(g`Sd^hzGyT7?*&YkVCT>$$Ck3UT!Lr=PB_e(~I&4o4_)so%?wD_@?_7vHxPPvvmU7h|xr;}o4GSm~@?!)ZF5@r$@9i$'
    'OIDnhE<-'
    'D|s3rz#L<l5Mqws%<G}X8D2(M<ecNBe(UCTmKM`wHX6lmnj2BEZYJ|+s|CwI=AMnmbOGy9d<MJ{N+U`d(RK#dxoQ7uZ5c1N'
    'e^pzBdhFbkY^{b+-0!1tc!r6~{q5(wdk6iE^}~L5sU{i{T>%WOsU&>%d>#^x>@p#}Y%0_Ln#Oa(5kdSE)wMbe6a&01`Zkm-'
    '*X%WBA;F|Sl;+;d?t?j@&Q&y+pQYyyng?9_EW+I?`R4l3`r#M-{*gde$^8R-pYWhh-'
    'pA`38~y#G{$|C5!2nRYk8)cXZ$RU>c1Y=+2$`d_OI^ow<8c1owez#Au<Kw}B#7R1+rqehbfWfPt?1~+kOH-UAGYsuNTXa^C'
    'EqlVf^`b66Xk;!bJCKwXWa`JO?aAgPVDzT)Mxo5fNRaM1v3DvJxo0Ht~5U?Qv#x!O94wJt2UleMmuz$u7J~pvzc0{s`=ekO'
    '|#Bxt|o)9iX})Ql|jBuRVcutB}>@jOeP-ga1lua+6$)6iX|JD-'
    '5hLmv^HedN7zAEHR)KfU`|?X3n>alX^iGJDH@!!#;dWX+{P%kEoCaAa5k9BFh?J@mz#&JPFJ88Q6SBP>5NLYH(O=zBo!@EL'
    'K)_Sy$_xwuBcYkK}k<S&34qfrh%g;5Vg4}IXYGGRf97eq~qD9x|zFHZ~w>bzuf-A?f(Hq=nvxUU%mbP58okfV57JE-'
    '==ZW)?gI<O4lTU(^Z2gCr7zV(}8pb4Q2^F-XaBVWeloD@I4{5wGt;r*-'
    '!XcaP45)%JHG@B#%+vAn3>20<%hv!z&UZ)T<m6fK6^ZGQo&g|MT@<tEyy^M<aVi8W<@J<Txsg$MQLOm@Cj?S8OMEw}%<Ni|'
    '~{WUl^8oLERU-?4X(gyybz60MAfa!4xT~Q)n{@6TYXS2hMqzn|m+jCpDR*aFV0Jr#@`49JFXxuZvu)_%rzuk^Ju-'
    'kJbwIZFX}i#Vj_Y3{ZC|H4;b5b{@tRS}8566?q$lnZ7b%&@J22YnJWawnsqxzLZ*BZ)OFOb-SD%G(=A_q9t1Yb=|9^w3i?I'
    'tNy3xnwKGVm(_DBAjhSbYiREw_th@SQe%3UaD|x<$M^$jL~jP;Sq_T+n4c|@WLZupV8~DA6!67nDp7?5m_xaR6qm$mtgT9r'
    '>skj@!|ALwM)d|)y-oGS-r*L=LWlePjYDy~3*yk;&Px)3u4O~4#V+G?i>t5v)i#mV%SD_P7vMnitZU=gH*-'
    'zN90LlMaf=YG@D+NB_Pj^RA<f{{GCD5g=2ZitZ11o0qONNv{JL*84)k}gGuM<mXK*Tj8JiAZq0)&dv{2+NQccc}`IYVE4ZI'
    '4SZWS3?2lT>Ai~l8{NbA%=4*ZYAW25FdX4g_K1*5MXq?a;$0UZs18^y_M%qb5F@KrJZ4xfNX;jj!&TA%y(Ov8}em51Tomfm'
    'D+_^c<AlHwU=XFY>8a|!;qE^g>v>ru1FpS_nww!#2(UOifTskPgV_UzAMHaFG*d^B6aY<bXuq@AG<#9#D01Cy%fuh3L<2Vg'
    'X_Nj0fPO011$I!?5XZP`}z(S*35mp8&u#1ha1&Kr;@m15|i&54YlngM)mHQ1~d;-'
    '?t80dh83E_hNMl*FS1XgR}J`kK`)$8mI=CDdMW3oN9&Wc4i<TDY1K@O`VB&Z6Gy%e1K-'
    '5CdY|+yTjIRS$}@m9~z;Q#s}c<yeY0d)2lu`mh~Py-ukG`3_s5lH#kB>)GKCMoCw*v|d!aBPK(OW~2yMCaY@+3+*YdbCbWt'
    'L}55l4(mrp2iu<?AN3FMN@NEFn6`YtOUh(M66?^L3kDoIDX^r|Qz8#{V#L<`V)h_;Rr(pA-'
    '5m>!iUL0lzdY7nk@!BR;P*LA7MR*F0}z2?1*IwiwQLc{)YFek!#JA7AP#40h;Bd>GzB-'
    '91DTvcQhrzMVmALGL)X>rHt?g~_&4_n)Dl7UWk@CAcNmXGQI?BQmQKX}E=H2djtm*$Ky8<e`JSUt+cc}}a*p)6(@pda_skX'
    '!oqaGlyjdoebm`uC{RCSa_K)0GQCb{YvcvBUzkG_shO)bU0_!pa_5SUDyZyhn|BoyTx8J}0?|=IH+duGi>kr?d-'
    '3&?9yZxW=$L&A=@SW%5t54+Va0YnJu9k-'
    'xC_#zOc0%iwqG)h&n!a(33jEj*SrocV`2m?$WICFkc9jE#qQ5n9nx<pv%~wr)OcAd1evqIbSKdt6ja+iN|Jd14?+3*od!Y?'
    'd#j3JCnMtK^U%mRk6p7x9sGhkifi?*|#K$ORq74datL!y2X@vhw`TNL-'
    'TJ!c8xxtPv(GG%caG_49st~5_8=P#o2v1#|Q1?-d-c-Asvbe}vE$7})e_kl_R?E878jqJP9GXE$erdW<Yiul?r|2fGJ66LT'
    'Nl$*h#w)@%d~m+9CUNrW#5;LKyQt?~OTagd6o4krQ`_|MxSS_?WBsWAeDC1v;ETPZt?ge2FQ2T5gD|<kxaM<dVZz7Jh4&)7'
    'h{O@}0)!Ax!tBZ`fs*NTV@lU2U*n570Zxvg(EQvo5e7(jZ0y7%7*IcqN;#)7M2nIYuz^diHpA2@!r0h=;-A>t-'
    'T9j6;vz{elM*Pth<V28$7l<fl|!_N?adXEXK5MG2O7u^wD%#d#8oL7c6iBq5?AfiP}duJ%gpydV5p{F(v2}OgG5P9`Xx7+&'
    ';XMlqCg}Y`1D~HgRU{ZPE$%FYE`3qv0B>|AsknLJs=tWLNX4>7X5H=-o}-'
    '{apAvGvTk=8dQwSzxI<h>nX5^B`>klTYO*P*JzAeYUttyFYiFl5$ZNHK6?cA<|Fr$9HKfJg<R2k5!atH8zdfJ<n-'
    '8)Ew)ro0E;bmitCq8r8Mn?RUK(K50{CQYZb{R9r~1rQOYJYg`%An;|4Jmfp5C#TZRa$Pve$SWrU#^kzyes3(hG{e!zxs4&S'
    'z_{H;=3&H`G<M&YMo-)nTJpQQA>va;2MAJ$f9*wbf_Cgq-'
    '6}UkJm_oB#C59b?o7jy_hTbB;b&=MPQM{%I+DK$VZT<YKa8M}d2d5*4)1!<_sj@KPL2h9JPedi({@YU?BWzTGU!N4Q)-'
    '$tJ#A1&b>N|3UB07;i29)gS{AFiT?K9V;?dRy`Kz$Wnc?|A(ul$xJ^AxwZq5bsXVnDMWw4RlZBIefQ-'
    'x%PQ}6@k%&=!#%K$U3thiCkq2McX%0Nm^?@)IZIv?u$@Hc2L_DknFwE}@sMrYBmyNO9gUXJVVs^2v!t8<SiweVXd89HO^i?'
    '9p?|Kmyt<?M{V6d_@p72oQy`;R6L3P=UBo8efF<kEJ(iS3aZLa_b8)du=&xA3u>_hsUTq9*aksWsX}~xX?ZZ}=H$e5kyCom'
    'M2|Nx^4hkqpARYxt6b+-Hw&H&57;)X^uD!RCTc9?QXP0AYHuqlWWU#EhMY&-'
    'GEuhxRgl2OdqL!4Q&;+YNuLkb!9a#VwiYwd0P6OTl3LQTy?+JHBs_qs^Yd~GwZ<wH#pjwW!WCS5n%9}{Mf%5KNMMK%8grfQ'
    'u(K30IIKtKYh!uFRS48@0=%)QKj9<4pi!uarIZ(qA@U2_qvaYssC-'
    '*d_SN+Vc<pNRmDk;C!TVLMkHa>%fj~JF4H9{j*qw`SHzCL$)O*((KH0MtF5lmGZ$(jDHCfwCk=nr!N^u*yEi^HouRX1$uKs'
    'L0*xH?;-mU*3LXiE!qgS+9n7VRb5V)@zXA1ChV6Z`|a67GxQCQRi8P`TK&pA(-'
    'Ow<Oc|8gH%o_qXpG$@B?e)k$WYfwm69*m;mA@pKyfNMT{0!XL&ifX|vA$>6XuTHurQ-uuFQ4KX<PN>|>?;&hjBzRTERSx(x'
    '%<E})uy#1RWzPtU$+wbB3{~`{#ffXRpXsuO4QU}hnazc0gjKm$maPFAXtdzo`*<7sfcn{FJ&E4Q#LSM84tJMM#JdXrx<<Qw'
    'E#9VhD(%e53ALh{%{~s6RjQb(*!^xDKSEPFkzA1~cvDttxKb8@MRxqJn8vZF?!P{UH(MRi^E+G@PSNg4Xrh3O6O6Md*C@qT'
    'V+kC3)-;_Fij%R0$-RUNkg)*JmAM3ic%k7TK57Rde!miWAq?|l-'
    'cbWAyn&*d%xNL^ER*kjaWEn6BzH<bC^t)cm*1enESJOLQmDG1@ZmVHv_9EOhxbng*iY094?B#l7>FtOHP|odu&LDKGhgrs|'
    'mf7tp`vc1IWOK(5iX<;Up0g6wjxu&uDEZ={K?BYgpdyA71XR&-'
    '$1_%tUP(f&XO@=LgFsc~Rz76p36gPEV8=8e50L8E&Oy_RvSno<o%`}=ZLxe?v}AZ!<Eek^&lKBA-'
    '8?Vjy7xX?{NAU!M0eWUUB7ulFSI6A@5=dFgdthX%C1ggNsG?oB&|-P7(z0o<|I1OK!0I-'
    'sotBW0&M*oM{pXYgISKw>X=;i$B~+T=15J{p^zPVjc>s;Y#zU~H}Ct-'
    's>Lt};rjg^6vWh_yG29%l81=y3YpFi&!d0fvq@&`1ZG(xLBP3__(gbzagBV#)s)1k5yUH*AOI;7gV=i>UXL_}P&bdIsryAA'
    'T!Lxn5IF>F%orZt8=(CHr@D)4S)@DZWt44%Ih+L!hBYJ5XR8L=6Y`lG`@M5)qGX%8&+59~<qeO-'
    '5g{FKS#!LBb#W+ui3{`DGojdrc|mr9WRgYW80%T^C@HbJ(xq^~BfQ%K)&C5rS4aH$r7>0|mj?cYCS{mR7f!lyc-'
    '8xO)j^ti{TMF`y*lRh3oVi2RKpm?SA9FOfijd9qZ*Rko|1dX4|BpF<qI&<qsR)IVPEV;hrsnc%UR9%8ZoGvJj2xoGo8VxFb'
    'dgTdPg}@%KaWdQtZt3Mp0?iUF6vnbdX<iWpNV+2HJzznNfx`nKCDehU-'
    '9WccQ#W@AZn7!v<?}fBBUhK<*TK*Y0o1VB?Mp&L-!#69Cs}0QeanfzDxqnPd2HV}XtQxL#UfAkWgCaz{NZH4?~qVXp-'
    'E<m9MJo*m{5BvOKBnesv5w~5zGsG1!m49$Jny34;*YxPq<t*mO93S4Hr#{g$I>?S=p>sDe&0R!aIEW@)Kyit^_jycO)&s0z'
    'l_ta6cfDEh0*2926FDMLX960&ph1}}6wlb{SjGXU3qM^)}#g<gW0rLS~^DP+lEQ|P!;h$cH8NS5AaT~y@$-'
    '{vrEVeg)s$6wY;6dvvit6Y-%gAwkV>I?952E)b$#iIY86lg-vCm^9s!sc!k9W$Kt!pC3h`mF7TyXM34Q}LXo-'
    'Mf(NNl^9vGLLtb~tTb^(rW!tmJpQGRyY$?q`NyyhI4fDvJJO*W6IuW$VV$IZ|WTvH#iwSC;Rt(C^sYW%YiqM(;aq-ukk4t`'
    'VDuU-3=rQ5w6-mA<*yZLmT&VEj1Iareq8+{Uu;-'
    'L0V6!~_L*MFTab{(r~F1#8VYV_hl!bCG8Q?s_`lez60!k)!Y6aBjr~=zCN=+No~63as&=13Ia7y-T+QRPT-'
    'LiUGK;<h);TvDOM#oGHPilrwJ*1-_6GWwpU|^ax9wm8cT6(keaPVd-uyWa)0bPfK^5wfnBbKkS1Yjfc2f+U=G$*0s8gMx1W'
    'N;9AGI+AXcV*TS+&ZDVRZsIqme7NS$$WG8irj7}~RYs@>tL{Eg0`oQd(<$eVKK5AJjWG&FoaDDDLzwBV``mlmI6fKWm6dv+'
    '8r-'
    '+<f262<PYSLm<qYLh~Fd4TM^4JD~)yH?oE>ky*7;NtxGfpiNqYCv(+}^2ZnU8q`V8?17I(|M<;*=I4j5NKE^vCHN_J}sZG0'
    'B0P$l)ILp`YU)I`Bf-'
    '0p61vK)0OTOKx16>D=H+tU>8&%K?w_{8kVae^|Oz8}e&jl2&g>x7;DtKgYII&M7p@IUZd;qZUyRJ&s>LGS&O#_U30l;Sl2<'
    'J!SMGy{x8sZFR&?eo`-'
    '$;q#iu2Rm&CL`Oa<vma*RB=>=(Gptsp@kz9&tM_^m?U6W4Ny;=feAGuMw`a=lp2=9p*>p&6UHRfU`V7VB!msj_75e_IRxxm'
    'KNZB+gKXH5BdywUWXhBm$V@h)Q#E%l<K)d7}$vP)|rq^dG<Nt=mz6|!>H+fq>dnTcE*r(dj9KPWM8}tm6R}yYaZ{L8VL^V!'
    'ct)48LGw+dhw84y2i6&>2D;YRV3c?~fE2)e_%NV=^Lq+W?kI!Jid<klMgsVuespVY}Pl&e^7^G34p2!&-'
    'XiJg~4X1!iS~r?$7<}KaJb7^#z|YS3%m{_lQi;4!2~J0pJmQkP8%YV)eMor9!%vOMq&}9-&ZA7_U1x0;x-'
    'r?6V2)Xo%@XS}I8f(oDd3#nKWI2fs|I*o-+7G+bZEz|N*YP-VN|jhpStY0q6~O;`Y5yL<v0E$9p2O>fVQXKn2otP+x6l4OF'
    'IcOj}adglC$hx%Rg>7k9y6WY}pv54IS6k*icor2&6e>a}AGI<Z@2r#ulLM&1YyfbVov`I!6*w`q+$E7?X)zG0^6a1_O{f{5'
    '$u;a!nUNcrc8jz1kI{*1ndt3TH#Dl`&=98*4z8>8`=xhnaxn(t!pgDX3cqup<%9Ibhhi^O1ZY$#0ZiIMeXK`qmNA(5Co_c-'
    'cSL-rA-'
    'F85Qb*Z@^Z2hLqi$Jjy00i<hKimPG^1qY}*GfH(=Jr<?My>)s0M(qm4XE3W?S_RoQ9E=QvgI(uP8mSi>+Ij8PR=+44=7fQa'
    '*!0GS#F+J^)?VKJ9`8X}W_Z^^oQ`dXv8$$cgqN2HX(j=8tY#=o$Y8M>G{2O&OO3-'
    'KDZx`}bUh7tKVvo#qJ<q+_Ug1`&^T&R=fIs%Uw|z_cl*js%_dt;EkhRy@@CW^kJ=oe`W3C(AguQFM%k;LcJ~0dDa{#l5$1y'
    '#*2rb(BDNwm>`If9s%i<#H25`cA+kCQ2)_f_JScU4AVi*q!lVPvBM7#h)X4f3UIGoxbPegjR$H_24gA@v@^2V~yheb%2p94'
    '6R(4MFSAc{jICWR@IvUJi#W|A0=q5uOv?#^N4CcRE-&LWFxHa_D~vA+XOP~-'
    'FFnA*(&Y+>=0T7eUcMa;4}sptC#2YUzT@@rP;hLQ<nP6iKbh;JoDc!hwmhp>+W=-'
    '<9?tb0fqZ+}M~brM{wQ8}qW?l>tJgc)1~oBZ+$)2=)P0w9dLEdmHN&G0L?in2pgdk*m<5uL0Jly*RG{x%v3w1f+T&Ehnpe0'
    '~7M*9F1ZEJTNu#CVyhqNaBNzTDo2f1+yam%4)DcYo|78~f&Tft9zH1ANld#yjQ_3Z`o2K|Y&c_+?O}0UFUT(xZKFyo*m~1q'
    'XY3N4yNwLuCcZcq-'
    '+2PkPg&lyR2cQs{X&$Nm0hu)cH9U*G&XAbF&uIoHjkXJ+cvm3y5g80zY>9)c>h+t+2a*Nf6y@X_lkE5O7evW<IST~3`lR!X'
    'PA^(rWgG@ZfHU6?VTe=fOQD9R|o?5RK81NA`^LF1?kqE$Iecxgrd*V~6jhhlHn%1~>OE{%|q%wEJ(v;=Xmo!%t%v78mcV_H'
    '-6)hg51-'
    'fp0KZ*}WQOX8}AWU5$W<ex@oaiX_2CC;mR9vAWDr1;YBm``<*hR^$3dk1}$Py3lph*uLP8Rr(P5L7Jm{X(v(ZkM(GU4(DaB'
    '%NGwlrL~6dU_l~Hd6}z2WDxkLyfnF4-4(N^M-NZ{^m#h%<bp>9<vUY-daCe-_b7-)3e0-'
    'KrNl1O{b$g9I<U60oiQ2y3g4`f;KpG@s1q5w0{@dSl(Cr!Pffr4l-*dx*m;03v=YKpn<meO*Tx_x8P&9-'
    'P$*JEw0?=2QmZm(2zIx0i^DnH<=u;CMkc{ep`Ttv(h+D-'
    'OK@IC29m{PR3EY#7!dVK*%p<<)$X#(&3lKvNdM#v74#QQEt0ozSqS=x?Pt;pAZ;FTWvZYYXiPqQ1Vt20Jwnyrl2k=%7Ni{{'
    '<@GH&o2qfsV)JXEG<=YH-mVJ$^(<_9QT<<p`P!J@l{hH--a@eGX+U%NW;TJU**}hzSh1Rb=PxK=0$c_DnKs5$_}e;xNB*$('
    'm32h<)bSH+~a@l?+~;&w_I>k#H}4(QjsX?wU$POWl^PNA;ks8>d&U++*a;mG5tlVF6vbgO4YlDSEBgvh?Qm6vNzMC@#yO0='
    '(gf`TWO{e7#{~dKbWDcr@2mP%a6*dTYt-v8=eB;rE~!R{ZG`D!FqBfLDH6xw@tZVevdn)MqPTw!;gO_p-EWm_GW1=>;T6m^'
    'qh^5Ec6FoZ6AFRNOSg~5@95DsG)7@i-hN>O^FpP8ZRrI2nbrK?R-myS1Xj<c$Q#>_cQgnB~LM67kV-'
    'y<B@g2%%Lj+bUadAVUD8~tWTTC8;=1L0$Kl}b|7M^{OuQRHh13LEs7*+$yv5^#=+{?N;+c8z5`%WF5*vJ2cTpfCyD@wAoJd'
    'J6{?jTq)9emft1!LppLwnL<tqgP?T5PtNAM1tY-?IY3DWYtm}G}Z%qy3rb&2`B&vsHDM+r(eV)Ys9%QUWWLx{eHUAO-'
    'R#wd&pI7rjh<Qfqi}l04_*fhsZ)||Fvvs^vXWRE4qE(^rXOFZ&k8)AEkUAwPR11)LH@+r6OB)MV#nXEVA8gC{TJW{1fMfM&'
    'gDISOC-pMCeHT*RMs?RA_AvFfqF*=OgKQ%Wn00yLB4&|=ao(+Z`1XFAr-'
    '?tDO{RJK`eN<1#Ql3hJvt^OIZ}O?58_yAXAO=J^%r9mS>!$(#E~x$O(?cJfKfm*zryb5>wg@t2<ZCmYo(FhSD9<gqq^2yFX'
    'd)RbnsM1h!)1~?xJql-nZ@ifwbgm;QzkLdb3z;iIMNulrIJ1iahWhYzJh(N13fn#`idp_I4bu*Ym_r#m|0jLQK64w7l#+7w'
    'gAIdoR|Hw)b|$`g43U^56dQZ^icRQUCeDIzD?PpT*ce{(NWq@QeO|^Db>oroZ)#qiv9?z7_296yViR?|L8f%yz&}Uj`i@6w'
    '1(Qv;i8@_U``i(VAG_-'
    '#^&H!(?N9cW;;8m;C&AcXOwINGUJv7F*l9P>Nmd?XKD49OcHune6sqcdOCcO*KZU@)(O+dDj>gjo-xCI6Vz9yN@hsFSwf+U'
    '(a{;J|}xue`{y^`4>k@EBJO^Fi4d|o+wKZ#wGUZ6bgs<O$43XMk%?9muIKWqO}G0<H+M>3G{T<Xs@K%JKvMYjcQSvTtTtFv'
    '%U-'
    'HBEOj4HKrVwt3_{<XVGuv6Khyfo}i{Sg^E*(o8$J?+1L0E2_d<KviS6_Pn|cwZmb8l?HA9>u0og7pcVvMeX$K?3MyG?>tRX'
    'Dt^>!)vx$D<Scd=B1F$2@D?#P_BpQ~;Kl!`1v|vfu>{9EmMX`j8YZu4fZYp1?<g1SIBiXqOn5gc9$1-'
    'QQyGhBkv+DG_zO%FURdBd{)DONofd7{Uun8Oth)`_oz1ZLBANA?p#ck0W;i*MgN$uMNQi(Bf?y&lhxEe!7Y+S_;mf8D>35;'
    '=_7%=jUH_te{y3Cl_AYYl50$edNh9i4@eA#3Y&nEsjM18%DSsuoC=6(T~1qOOpvfH2mm%@4_5FamH<kz;!%!nFeJS@&ZMST'
    '46$E$FNokutt`2CAdR&P2LXIL2~j4`iti36Y7)mrq<vCNR8pPbs+gChkFNaP25$49}7!-'
    '_>JPD+W#%#J3D1B@6Ll;+{EDN*v#;j=aVEfrg(Sw~tq6{=Id9al<u{%V?>$lLJhD+!Ak1xr#_YhG|*Z9~VfalG6A^?rW?&u'
    '?|Nf+x-KL0`!;txhA9MJ#>~kl22VtI~#rT0mmwgSTaiP%h|NqEOp}Jfcc8J>P{}yBXa>T9B7xO7b#B+l6F>MV3-'
    'Bs;5$(;AMd2G&#CGbY~*-5G+Wrz1g)&80k>-'
    'D$LRAsGW6aBa(C>ORYo_UYS#)&8hT>YxA3!NCLs;_JLU8QOM!>sAzi~A9H0zoPWSly=A33b-7D+;H2n1K^s*vNbx0*o;NE-'
    '%Rkq7?c}@Vz>~AeTqrxUZ`~}EEIB9AMPJ4)KLkd}W^p2)mB8zq;Q|2R^L3L~i16lJ=X*CNmR)!8u}f9t#1hp?C#kWxu~a61'
    'le{)dOlg289xIDnQ6Z9QN>^xhSeAeoEgfT1;_v*oBkb9;DDN_u{qYXHl99=WGp^MnZ)^)z=GSTJScO>#RB(h}TSk#sRg%e4'
    'j0p&M=Mo|VzEBNhmJ{}GKD@#=srzr@qRnbuXX*a~)SJz6'
)

def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def main() -> int:
    root = Path(__file__).resolve().parent
    target = root / "phase4" / "publisher.py"
    print("Project root:    ", root)
    print("Target Publisher:", target)
    if not (root / "run_ui.py").is_file() or not target.is_file():
        print("ERROR: Put this installer NEXT TO run_ui.py in the V4.0.6 project root.")
        return 1
    current = target.read_bytes()
    actual = sha256(current)
    print("Current SHA256:  ", actual)
    if actual == V2_SHA:
        print("ALREADY INSTALLED: V2 Publisher SHA256 verified. No change necessary.")
        return 0
    if actual not in (BASE_SHA, V1_SHA):
        print("REFUSING TO OVERWRITE UNKNOWN CODE; backup and inspect current Publisher manually.")
        print("Expected base/V1 hash but found:", actual)
        return 2
    try:
        patched = zlib.decompress(base64.b85decode(PAYLOAD))
    except Exception as exc:
        print("ERROR: Installer payload is damaged:", exc)
        return 3
    if sha256(patched) != V2_SHA:
        print("ERROR: Patched Publisher SHA256 doesn't match! No changes made.")
        return 4
    backup = target.with_name(
        "publisher.py.backup_before_hotfix_v2_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    )
    shutil.copy2(target, backup)
    print("Backup saved:    ", backup)
    temp = target.with_name("publisher.py.tmp_hotfix_v2")
    try:
        temp.write_bytes(patched)
        if sha256(temp.read_bytes()) != V2_SHA:
            raise RuntimeError("Temporary source failed checksum verification")
        os.replace(temp, target)
    finally:
        if temp.exists():
            temp.unlink()
    saved = target.read_bytes()
    print("Installed SHA256:", sha256(saved))
    print("V2 marker:       ", b"CATEGORY_HOTFIX_V2" in saved)
    print("Runtime marker:  ", b"CATEGORY HOTFIX V2 ACTIVE" in saved)
    if sha256(saved) != V2_SHA:
        print("ERROR: Installation verification failed. Restore backup:", backup)
        return 5
    print("PASS: Hotfix V2 installed successfully at the correct path.")
    print("Next: python verify_publisher_hotfix.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())

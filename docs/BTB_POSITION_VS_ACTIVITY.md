# BreakTheBank — Position vs Activity comparison

Wallet `0xf031…1106c80c` · generated 2026-09-05 · one row per (market, outcome).

Only the **unverified remainder** is listed: the 258 adoptable and 374 expired-consistent groups (632 of 738) were verified separately and are excluded here.

## At a glance

| Activity match | Groups | Stored PnL | Activity PnL | Meaning |
|---|---:|---:|---:|---|
| Direct fill match | 87 | 963,773.62 | 2,325,702.40 | fills found under the market id itself |
| Same-event slug | 12 | -5,749,993.84 | shared, see below | no fills under the id; the event has same-outcome fills |
| Nil (nothing anywhere) | 7 | -2,595,150.35 | — | no trade, redeem, split or transfer on record |

## Largest gaps (top 10, direct matches only)

Slug-shared rows are excluded here — their act columns repeat one event's fills (see section below).

| market | outcome | db_pnl | act_pnl | diff |
|---|---|---:|---:|---:|
| Will Japan win on 2026-06-29? | No | 0.00 | -1,195,635.38 | -1,195,635.38 |
| Will Morocco win on 2026-07-09? | No | 0.00 | -1,053,047.06 | -1,053,047.06 |
| Will Norway win on 2026-07-11? | No | -132,458.97 | -1,079,854.51 | -947,395.54 |
| Will Argentina win on 2026-07-19? | No | -81,885.73 | -943,840.83 | -861,955.09 |
| Will Brazil win on 2026-06-29? | Yes | 788,101.65 | 1,523,241.02 | 735,139.37 |
| Will Norway vs. England end in a draw? | Yes | 15,273.71 | 731,723.68 | 716,449.98 |
| Will Arsenal FC win on 2026-08-16? | No | -107.84 | -714,999.97 | -714,892.13 |
| Will England win on 2026-07-11? | Yes | -560,227.23 | 152,760.58 | 712,987.82 |
| Will Spain vs. Argentina end in a draw? | Yes | 1,412,059.50 | 2,118,089.25 | 706,029.75 |
| Will Spain win on 2026-07-19? | Yes | -688,805.03 | -42,499.87 | 646,305.17 |

## Legend

- `db_bought` = stored shares bought · `db_cost` = stored cost basis (shares × avg) · `db_pnl` = stored realized PnL
- `act_buys` / `act_cost` = fills from activity · `act_pnl` = fills proceeds minus fills cost · `diff` = act_pnl − db_pnl
- `nil` = no activity under the market id nor its event slug

### Direct matches — fills under the market id (87 rows)

| market id | market | outcome | verdict | db_bought | db_cost | db_pnl | act_buys | act_cost | act_pnl | diff |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `0x085e6d64db` | Will Japan win on 2026-06-29? | No | DIRECT | 1,470,282.19 | 1,192,986.97 | 0.00 | 1,470,282.19 | 1,195,635.38 | -1,195,635.38 | -1,195,635.38 |
| `0x17e6ca6b83` | Will Morocco win on 2026-07-09? | No | DIRECT | 1,224,473.32 | 1,053,047.05 | 0.00 | 1,224,473.32 | 1,053,047.06 | -1,053,047.06 | -1,053,047.06 |
| `0x4b84a8e08c` | Will Norway win on 2026-07-11? | No | DIRECT | 1,430,646.05 | 1,101,454.40 | -132,458.97 | 1,430,646.05 | 1,089,407.26 | -1,079,854.51 | -947,395.54 |
| `0x0c9ea0b150` | Will Argentina win on 2026-07-19? | No | DIRECT | 1,292,932.64 | 943,840.82 | -81,885.73 | 1,292,932.64 | 943,840.83 | -943,840.83 | -861,955.09 |
| `0xf95968b133` | Will Brazil win on 2026-06-29? | Yes | DIRECT | 120,360.97 | 60,722.11 | 788,101.65 | 120,360.97 | 67,402.14 | 1,523,241.02 | 735,139.37 |
| `0xdbbbbd6ea7` | Will Norway vs. England end in a draw? | Yes | DIRECT | 55,000.00 | 26,334.00 | 15,273.71 | 55,000.00 | 13,887.50 | 731,723.68 | 716,449.98 |
| `0xbfbf42bef7` | Will Arsenal FC win on 2026-08-16? | No | DIRECT | 165.91 | 107.84 | -107.84 | 1,099,999.96 | 714,999.97 | -714,999.97 | -714,892.13 |
| `0x0f5e01cf1c` | Will England win on 2026-07-11? | Yes | DIRECT | 1,120,454.47 | 560,227.23 | -560,227.23 | 0.00 | 0.00 | 152,760.58 | 712,987.82 |
| `0x51166276fa` | Will Spain vs. Argentina end in a draw? | Yes | DIRECT | 2,118,089.25 | 705,959.15 | 1,412,059.50 | 0.00 | 0.00 | 2,118,089.25 | 706,029.75 |
| `0xdfbaae9f75` | Will Spain win on 2026-07-19? | Yes | DIRECT | 1,392,932.32 | 688,805.03 | -688,805.03 | 99,999.68 | 42,499.87 | -42,499.87 | 646,305.17 |
| `0x48e6e5108d` | Will Paraguay win on 2026-06-29? | Yes | DIRECT | 1,241,997.01 | 618,017.71 | -618,017.71 | 6,855.33 | 548.43 | -548.43 | 617,469.28 |
| `0xffa0580096` | Will United States vs. Australia end in a dr | Yes | DIRECT | 1,289,485.59 | 618,179.39 | -618,179.39 | 91,394.23 | 19,192.79 | -19,192.79 | 598,986.60 |
| `0x64ae6964dd` | Exact Score: Spain 0 - 3 Argentina? | Yes | DIRECT | 1,002,412.15 | 500,003.18 | -500,003.18 | 2,413.18 | 19.31 | -19.31 | 499,983.88 |
| `0x605ca8a924` | Exact Score: Spain 0 - 1 Argentina? | Yes | DIRECT | 1,202,282.76 | 516,139.99 | -516,139.99 | 202,283.79 | 16,182.70 | -16,182.70 | 499,957.29 |
| `0x8860c80389` | Exact Score: Spain 1 - 0 Argentina? | Yes | DIRECT | 1,022,371.97 | 502,393.59 | -502,393.59 | 22,373.00 | 2,461.03 | -2,461.03 | 499,932.56 |
| `0xdfbaae9f75` | Will Spain win on 2026-07-19? | No | DIRECT | 825,156.61 | 474,134.99 | 0.00 | 825,156.61 | 474,214.25 | -474,214.25 | -474,214.25 |
| `0x417b5575a4` | Exact Score: Spain 3 - 3 Argentina? | No | DIRECT | 499,999.98 | 491,499.98 | -20,911.76 | 499,999.98 | 491,499.98 | -491,499.98 | -470,588.22 |
| `0x53da62774d` | Exact Score: Spain 2 - 3 Argentina? | No | DIRECT | 499,998.99 | 482,499.03 | -11,911.74 | 499,998.99 | 482,499.03 | -482,499.03 | -470,587.28 |
| `0xb1fca83dd9` | Will Australia win on 2026-06-19? | No | DIRECT | 674,512.35 | 553,100.13 | -103,425.23 | 674,512.35 | 553,100.13 | -553,100.13 | -449,674.90 |
| `0xc09537a097` | Will France win on 2026-07-09? | Yes | DIRECT | 1,317,627.69 | 439,165.31 | 878,418.46 | 0.00 | 0.00 | 1,317,627.69 | 439,209.23 |
| `0x02c913fd89` | Will Club Atlético de Madrid win on 2026-08- | No | DIRECT | 633,455.20 | 209,040.21 | 213,258.27 | 633,455.20 | 209,040.21 | -209,040.21 | -422,298.49 |
| `0x017f79842c` | Will Germany vs. Paraguay end in a draw? | Yes | DIRECT | 1,235,141.68 | 411,672.72 | 823,427.78 | 0.00 | 0.00 | 1,235,141.68 | 411,713.89 |
| `0xf95968b133` | Will Brazil win on 2026-06-29? | No | DIRECT | 549,984.64 | 230,993.55 | 135,662.88 | 549,984.64 | 230,993.55 | -230,993.55 | -366,656.43 |
| `0x3b9204e0fc` | Will France vs. Spain end in a draw? | Yes | DIRECT | 762,224.15 | 373,489.83 | -373,489.83 | 37,243.37 | 11,079.90 | -11,079.90 | 362,409.93 |
| `0x2fb15810a8` | Will Manchester City win on 2026-08-16? | Yes | DIRECT | 1,800,147.50 | 610,610.03 | -610,610.03 | 744,443.99 | 267,999.84 | -251,529.48 | 359,080.55 |
| `0x20fac1c925` | Will France win on 2026-07-14? | No | DIRECT | 524,980.78 | 312,311.07 | 39,873.58 | 524,980.78 | 310,113.61 | -310,113.61 | -349,987.19 |
| `0x7ebb071347` | Will United States win on 2026-06-19? | No | DIRECT | 947,695.93 | 361,925.08 | -17,138.00 | 947,695.93 | 366,280.80 | -366,280.80 | -349,142.80 |
| `0x36fca44fa1` | Will Belgium win on 2026-07-10? | Yes | DIRECT | 20,169.59 | 9,881.08 | -272,506.52 | 20,169.59 | 3,176.71 | 63,699.87 | 336,206.40 |
| `0xdac6e67bfc` | Will Germany win on 2026-06-29? | No | DIRECT | 1,342,789.06 | 352,079.29 | 79,419.01 | 1,342,789.06 | 359,125.16 | -251,477.77 | -330,896.78 |
| `0xaa23528a8f` | Will Spain win on 2026-07-14? | Yes | DIRECT | 259,646.29 | 118,710.28 | 287,840.46 | 259,646.29 | 76,571.54 | 602,750.50 | 314,910.04 |
| `0xb025924a63` | Will Spain vs. Belgium end in a draw? | Yes | DIRECT | 603,711.69 | 281,691.87 | -281,691.87 | 99,999.72 | 24,249.93 | 17,517.73 | 299,209.60 |
| `0x2c37e07b72` | Will Spain win on 2026-07-10? | No | DIRECT | 845,285.70 | 340,227.50 | -340,227.50 | 1,517,755.90 | 612,577.92 | -612,577.92 | -272,350.43 |
| `0xc09537a097` | Will France win on 2026-07-09? | No | DIRECT | 397,943.80 | 147,239.21 | 90,812.41 | 397,943.80 | 147,239.21 | -147,239.21 | -238,051.61 |
| `0x7ebb071347` | Will United States win on 2026-06-19? | Yes | DIRECT | 674,512.35 | 224,814.97 | 186,615.15 | 0.00 | 0.00 | 411,452.61 | 224,837.46 |
| `0x0c9ea0b150` | Will Argentina win on 2026-07-19? | Yes | DIRECT | 5.19 | 1.73 | -1.73 | 0.00 | 0.00 | 216,602.25 | 216,603.98 |
| `0xa90ce8b69a` | Will Ecuador win on 2026-06-20? | No | DIRECT | 375,036.29 | 56,255.44 | 229,080.32 | 375,036.29 | 56,255.44 | 49,679.26 | -179,401.05 |
| `0x375409bc5e` | Will England win the 2026 FIFA World Cup? | Yes | DIRECT | 3,041,766.35 | 307,826.75 | -307,826.75 | 4,228,179.62 | 430,047.00 | -129,884.44 | 177,942.31 |
| `0x17e6ca6b83` | Will Morocco win on 2026-07-09? | Yes | DIRECT | 310,604.16 | 155,302.08 | -155,302.08 | 0.00 | 0.00 | 19,547.87 | 174,849.95 |
| `0xc17c0b2fba` | Will Ghana vs. Panama end in a draw? | No | DIRECT | 969,503.45 | 668,666.53 | 300,816.56 | 719,503.45 | 496,262.33 | 473,241.11 | 172,424.55 |
| `0x53da62774d` | Exact Score: Spain 2 - 3 Argentina? | Yes | DIRECT | 303,795.21 | 151,897.60 | -151,897.60 | 0.00 | 0.00 | 7,651.99 | 159,549.59 |
| `0x0256ef6342` | Will Ghana win on 2026-06-17? | Yes | DIRECT | 2,135,551.37 | 843,756.34 | 1,291,590.01 | 1,785,551.37 | 707,720.55 | 1,427,830.82 | 136,240.81 |
| `0x2037b257e6` | France vs. Morocco: O/U 2.5 | Under | DIRECT | 511,110.00 | 267,054.97 | 244,055.02 | 255,555.00 | 133,527.49 | 377,582.51 | 133,527.49 |
| `0xaa23528a8f` | Will Spain win on 2026-07-14? | No | DIRECT | 200,000.00 | 140,000.00 | -6,666.67 | 200,000.00 | 140,000.00 | -140,000.00 | -133,333.33 |
| `0xd8aff2490e` | Will Bosnia and Herzegovina win on 2026-07-0 | No | DIRECT | 349,984.02 | 311,485.78 | -23,128.86 | 349,984.02 | 311,485.78 | -146,383.06 | -123,254.20 |
| `0x5eb6a7f6e7` | Will Club Atlético de Madrid vs. Málaga CF e | Yes | DIRECT | 638,737.63 | 105,519.46 | -105,519.46 | 5,289.90 | 1,057.98 | -1,057.98 | 104,461.48 |
| `0xb1fca83dd9` | Will Australia win on 2026-06-19? | Yes | DIRECT | 30,556.19 | 15,278.10 | -15,278.10 | 0.00 | 0.00 | 88,744.11 | 104,022.20 |
| `0xbbb20aee74` | Will England win on 2026-07-15? | No | DIRECT | 149,998.59 | 96,749.09 | 3,249.97 | 149,998.59 | 96,749.09 | -96,749.09 | -99,999.06 |
| `0xe2671b2075` | Will United States vs. Bosnia and Herzegovin | Yes | DIRECT | 207,160.11 | 96,433.03 | -96,433.03 | 22,278.82 | 4,010.19 | -4,010.19 | 92,422.85 |
| `0xe70fd51f42` | Will IR Iran win on 2026-06-15? | No | DIRECT | 839,664.99 | 386,245.90 | 453,419.09 | 639,664.99 | 294,245.90 | 545,419.09 | 92,000.00 |
| `0x9e030ad2c9` | Will Curaçao win on 2026-06-20? | Yes | DIRECT | 269,101.58 | 89,691.56 | -74,361.77 | 0.00 | 0.00 | 15,338.78 | 89,700.55 |
| `0xa6cd933c6c` | Will Ecuador vs. Curaçao end in a draw? | Yes | DIRECT | 397,897.14 | 102,538.09 | 295,317.06 | 128,795.56 | 12,879.56 | 385,017.58 | 89,700.53 |
| `0x3b9204e0fc` | Will France vs. Spain end in a draw? | No | DIRECT | 104,690.12 | 72,236.18 | -2,442.77 | 104,690.12 | 72,236.18 | -72,236.18 | -69,793.41 |
| `0x8a3ca97b10` | Will France vs. Morocco end in a draw? | No | DIRECT | 220,524.50 | 165,393.38 | -4,864.86 | 220,524.50 | 165,393.38 | -66,967.75 | -62,102.90 |
| `0x5fac5a47f1` | Will Scotland win on 2026-06-19? | Yes | DIRECT | 169,173.53 | 69,141.22 | -69,141.22 | 45,372.19 | 7,259.55 | -7,259.55 | 61,881.67 |
| `0xe9d96f957f` | Will United States win on 2026-07-01? | Yes | DIRECT | 184,881.30 | 61,620.94 | 93,203.56 | 0.00 | 0.00 | 154,830.69 | 61,627.13 |
| `0x8ea0b72b4f` | Exact Score: Spain 0 - 0 Argentina? | Yes | DIRECT | 1,000,351.09 | 58,820.64 | 941,488.89 | 352.12 | 38.73 | 1,000,312.36 | 58,823.47 |
| `0xbc28e92d1f` | Will Morocco win on 2026-06-19? | No | DIRECT | 819,914.18 | 352,563.10 | -352,563.10 | 943,715.51 | 407,096.18 | -407,096.18 | -54,533.08 |
| `0xdf13369a5e` | Will England vs. Argentina end in a draw? | Yes | DIRECT | 149,998.59 | 49,994.53 | 249.97 | 0.00 | 0.00 | 50,249.50 | 49,999.53 |
| `0xadf4acda3a` | Will Argentina win on 2026-07-15? | Yes | DIRECT | 149,998.59 | 49,994.53 | -3,124.81 | 0.00 | 0.00 | 46,874.72 | 49,999.53 |
| `0x7061e7ce4d` | Will Korea Republic win on 2026-06-11? | Yes | DIRECT | 1,102,120.77 | 407,784.68 | 694,336.09 | 1,006,565.77 | 372,429.33 | 729,691.44 | 35,355.35 |
| `0x990a59036a` | Will Crystal Palace win the 2026-27 English  | Yes | DIRECT | 400,000.00 | 16,640.00 | -16,266.67 | 0.00 | 0.00 | 400.00 | 16,666.67 |
| `0x04b6d6630d` | Will France win on 2026-06-16? | No | DIRECT | 828,798.26 | 273,171.91 | -273,171.91 | 1,548,261.22 | 507,901.61 | -263,984.77 | 9,187.14 |
| `0x649bd3dc84` | Will Morocco win on 2026-06-24? | No | DIRECT | 476,903.98 | 78,879.92 | -78,879.92 | 485,646.93 | 88,491.91 | -86,743.32 | -7,863.40 |
| `0x3a26ca6425` | Will Switzerland win the 2026 FIFA World Cup | Yes | DIRECT | 9,269,589.87 | 103,819.41 | -103,819.41 | 9,987,074.06 | 116,089.24 | -108,914.40 | -5,095.00 |
| `0xd14544ac73` | Will Brazil win on 2026-06-24? | No | DIRECT | 491,589.35 | 118,030.60 | -118,030.60 | 491,589.36 | 122,897.34 | -122,897.34 | -4,866.73 |
| `0x6fcd127dbe` | Will Morocco vs. Haiti end in a draw? | Yes | DIRECT | 372,638.33 | 40,170.41 | -40,170.41 | 372,638.33 | 44,716.60 | -44,716.60 | -4,546.19 |
| `0x7ea6ae7cbd` | Will Manchester City FC win on 2026-08-28? | No | DIRECT | 234,320.59 | 93,728.24 | -93,728.24 | 478,758.09 | 191,503.24 | -91,283.86 | 2,444.37 |
| `0x4f3421fb2d` | Will Portugal win the 2026 FIFA World Cup? | Yes | DIRECT | 683,314.42 | 37,377.30 | -37,377.30 | 928,388.89 | 51,554.00 | -35,869.23 | 1,508.07 |
| `0xff081c5248` | Will Bulgaria win Eurovision 2026? | No | DIRECT | 22,257.46 | 20,227.58 | -20,227.58 | 43,564.74 | 39,597.14 | -19,483.07 | 744.51 |
| `0x0d2071920d` | Will Algeria win on 2026-06-22? | No | DIRECT | 692,315.64 | 237,325.80 | -237,325.80 | 756,399.89 | 259,739.98 | -236,669.64 | 656.16 |
| `0x32cfa52198` | Will Belgium win the 2026 FIFA World Cup? | Yes | DIRECT | 2,413,355.16 | 30,649.61 | -30,649.61 | 2,413,355.16 | 31,303.15 | -31,303.15 | -653.54 |
| `0x30d55d8124` | Will Brazil win the 2026 FIFA World Cup? | Yes | DIRECT | 2,377,072.74 | 148,091.63 | -141,437.85 | 2,377,072.74 | 148,175.64 | -142,009.67 | -571.82 |
| `0x415cb64cfa` | Will Qatar win on 2026-06-13? | Yes | DIRECT | 108,962.78 | 4,903.33 | -4,903.33 | 153,592.34 | 6,911.66 | -4,457.03 | 446.30 |
| `0x7034c00a24` | Will Lionel Messi win the 2026 Ballon d'Or? | Yes | DIRECT | 36,728.25 | 411.36 | 587.97 | 0.00 | 0.00 | 1,001.18 | 413.22 |
| `0x26f410f751` | Will Ousmane Dembélé win the 2026 Ballon d'O | Yes | DIRECT | 36,728.25 | 411.36 | -8.68 | 0.00 | 0.00 | 404.01 | 412.69 |
| `0x3d5321854a` | Will Michael Olise win the 2026 Ballon d'Or? | Yes | DIRECT | 36,728.25 | 411.36 | -302.51 | 0.00 | 0.00 | 110.18 | 412.69 |
| `0x9f50939c39` | Will Khvicha Kvaratskhelia win the 2026 Ball | Yes | DIRECT | 36,728.25 | 411.36 | -45.39 | 0.00 | 0.00 | 367.28 | 412.68 |
| `0x6680cae9b3` | Will Israel win Eurovision 2026? | Yes | DIRECT | 105,001.83 | 22,984.90 | -22,984.90 | 105,001.83 | 22,752.79 | -22,752.79 | 232.12 |
| `0x7d9ee25265` | Morocco vs. Haiti: O/U 1.5 | Under | DIRECT | 12,221.95 | 2,187.73 | -2,187.73 | 12,221.95 | 2,261.77 | -2,261.77 | -74.04 |
| `0x2153377bdb` | Will Netherlands win on 2026-06-14? | Yes | DIRECT | 321,897.99 | 144,435.63 | -25,359.36 | 321,897.99 | 146,902.27 | -25,409.57 | -50.21 |
| `0xe24c3f7d4c` | Will Malta win Eurovision 2026? | Yes | DIRECT | 221,341.36 | 1,062.44 | -1,062.44 | 221,341.36 | 1,104.11 | -1,104.11 | -41.67 |
| `0x0c4cd2055d` | Will Argentina win the 2026 FIFA World Cup? | No | DIRECT | 88,497.84 | 51,399.54 | 278.07 | 88,497.84 | 51,411.09 | 272.90 | -5.18 |
| `0x0c4cd2055d` | Will Argentina win the 2026 FIFA World Cup? | Yes | DIRECT | 1,374,234.10 | 236,230.84 | 319,806.95 | 1,374,234.10 | 231,144.11 | 319,805.78 | -1.17 |
| `0x6698f3324b` | Lakers vs. Mavericks | Mavericks | DIRECT | 306,418.68 | 119,503.29 | -119,503.29 | 308,740.19 | 120,408.67 | -119,503.29 | -0.00 |
| `0x8058ed757c` | Exact Score: France 3 - 0 Spain? | Yes | DIRECT | 6,661.26 | 179.85 | -179.85 | 25,574.18 | 690.50 | -179.85 | -0.00 |
| `0x3bb3f35e86` | Will Bosnia and Herzegovina win on 2026-06-1 | No | DIRECT | 561,023.78 | 448,819.02 | 112,204.76 | 561,023.78 | 448,819.02 | 112,204.76 | -0.00 |
| `0x971eb98daa` | Will Egypt win on 2026-07-07? | No | DIRECT | 245,415.11 | 225,781.90 | 19,633.21 | 245,415.10 | 225,781.90 | 19,633.21 | 0.00 |

*Subtotal — db_pnl 963,773.62 | act_pnl 2,325,702.40*

### Slug matches — shared event evidence, do not sum act columns (12 rows)

> Each row repeats its whole event's same-outcome fills. They are shared evidence per event, not per-leg sums.

| market id | market | outcome | verdict | db_bought | db_cost | db_pnl | act_buys | act_cost | act_pnl | diff |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `0x8e1a6b6f91` | Exact Score: Spain 0 - 2 Argentina? | Yes | SLUG_LINKED | 999,998.97 | 499,999.49 | -499,999.49 | 227,422.09 | 18,701.77 | 989,301.30 | 1,489,300.79 |
| `0x8e5ca27d3d` | Exact Score: Spain 3 - 1 Argentina? | Yes | SLUG_LINKED | 999,998.97 | 499,999.49 | -499,999.49 | 227,422.09 | 18,701.77 | 989,301.30 | 1,489,300.79 |
| `0x9ad2c0508c` | Exact Score: Spain 2 - 2 Argentina? | Yes | SLUG_LINKED | 999,998.97 | 499,999.49 | -499,999.49 | 227,422.09 | 18,701.77 | 989,301.30 | 1,489,300.79 |
| `0xa196eef1b1` | Exact Score: Spain 1 - 1 Argentina? | Yes | SLUG_LINKED | 999,998.97 | 499,999.49 | -499,999.49 | 227,422.09 | 18,701.77 | 989,301.30 | 1,489,300.79 |
| `0xa591124b82` | Exact Score: Spain 2 - 0 Argentina? | Yes | SLUG_LINKED | 999,998.97 | 499,999.49 | -499,999.49 | 227,422.09 | 18,701.77 | 989,301.30 | 1,489,300.79 |
| `0xbdef8b9cd2` | Exact Score: Spain 3 - 0 Argentina? | Yes | SLUG_LINKED | 999,998.97 | 499,999.49 | -499,999.49 | 227,422.09 | 18,701.77 | 989,301.30 | 1,489,300.79 |
| `0xbe832aed1b` | Exact Score: Any Other Score? | Yes | SLUG_LINKED | 999,998.97 | 499,999.49 | -499,999.49 | 227,422.09 | 18,701.77 | 989,301.30 | 1,489,300.79 |
| `0xc0323c82e7` | Exact Score: Spain 2 - 1 Argentina? | Yes | SLUG_LINKED | 999,998.97 | 499,999.49 | -499,999.49 | 227,422.09 | 18,701.77 | 989,301.30 | 1,489,300.79 |
| `0xea3a43cfe4` | Exact Score: Spain 1 - 2 Argentina? | Yes | SLUG_LINKED | 999,998.97 | 499,999.49 | -499,999.49 | 227,422.09 | 18,701.77 | 989,301.30 | 1,489,300.79 |
| `0xf78d593533` | Exact Score: Spain 1 - 3 Argentina? | Yes | SLUG_LINKED | 999,998.97 | 499,999.49 | -499,999.49 | 227,422.09 | 18,701.77 | 989,301.30 | 1,489,300.79 |
| `0xff981ecb33` | Exact Score: Spain 3 - 2 Argentina? | Yes | SLUG_LINKED | 999,998.97 | 499,999.49 | -499,999.49 | 227,422.09 | 18,701.77 | 989,301.30 | 1,489,300.79 |
| `0x417b5575a4` | Exact Score: Spain 3 - 3 Argentina? | Yes | SLUG_LINKED | 499,998.99 | 249,999.49 | -249,999.49 | 227,422.09 | 18,701.77 | 989,301.30 | 1,239,300.80 |

*Subtotal — db_pnl -5,749,993.84 | act_pnl 11,871,615.63*

### Nil — no activity anywhere (7 rows)

> Booked cost on these rows has no receipt. Candidates for exclusion, never for correction.

| market id | market | outcome | verdict | db_bought | db_cost | db_pnl | act_buys | act_cost | act_pnl | diff |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `0x085e6d64db` | Will Japan win on 2026-06-29? | Yes | DEAD | 549,984.64 | 274,992.32 | -274,992.32 | nil | nil | nil | nil |
| `0x20fac1c925` | Will France win on 2026-07-14? | Yes | DEAD | 304,690.12 | 152,345.06 | -152,345.06 | nil | nil | nil | nil |
| `0x3e5ad7b791` | Will Málaga CF win on 2026-08-19? | Yes | DEAD | 633,447.73 | 211,128.13 | -211,149.24 | nil | nil | nil | nil |
| `0x4a07da4e47` | Will Arsenal FC vs. Manchester City end in a | Yes | DEAD | 1,099,834.05 | 357,446.07 | -357,446.07 | nil | nil | nil | nil |
| `0x577cffeb67` | Will Scotland vs. Morocco end in a draw? | Yes | DEAD | 123,801.33 | 61,900.67 | -61,900.67 | nil | nil | nil | nil |
| `0x8a3ca97b10` | Will France vs. Morocco end in a draw? | Yes | DEAD | 1,581,550.74 | 527,130.86 | -527,183.58 | nil | nil | nil | nil |
| `0x8eb933271b` | Will Brazil vs. Japan end in a draw? | Yes | DEAD | 2,020,266.83 | 1,010,133.42 | -1,010,133.42 | nil | nil | nil | nil |

*Subtotal — db_pnl -2,595,150.35*

## Method note

Outcome labels are normalized before matching (case, surrounding space and punctuation stripped, so `Côte d'Ivoire` meets `Cote dIvoire`). Event-slug fallback links multi-outcome legs whose fills sit under sibling condition IDs. Source tables: `wallet_closed_positions_v2`, `tmp_btb_activity` (249,851 events), `markets_v2`. Rebuild with `scratch` temp scripts + `tmp_btb_verdict`.


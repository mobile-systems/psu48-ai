# Справочные материалы (datasheets)

Руководства/даташиты по компонентам, использованные при проектировании PSU48-800.
Скачаны для локального хранения (сторонние ресурсы st.com/alldatasheet могут блокировать
прямой доступ или менять адреса).

| Файл | Компонент | Издатель | Источник |
|------|-----------|----------|----------|
| `UCC24624.pdf` | 2-channel LLC synchronous-rectifier controller (SOIC-8, VD≤230 В) | TI | https://www.ti.com/lit/ds/symlink/ucc24624.pdf |
| `UCC24610.pdf` | SR controller (не применён: VD max 50 В) | TI | https://www.ti.com/lit/ds/symlink/ucc24610.pdf |
| `UC3854.pdf` | Average-current-mode PFC controller | TI (UC family) | https://www.ti.com/lit/ds/symlink/uc3854.pdf |
| `L6599A_farnell.pdf` | Improved high-voltage resonant (LLC) controller; тот же TSOP-16, что L6599 | ST, копия Farnell | https://www.farnell.com/datasheets/1876813.pdf (оригинал: https://www.st.com/resource/en/datasheet/l6599a.pdf — st.com блокирует скачивание из скриптов) |
| `TinySwitch4_TNY284-290.pdf` | TNY290P offline switcher (PDIP-8C) | Power Integrations | https://www.power.com/sites/default/files/documents/tinyswitch-4_family_datasheet.pdf |
| `INA181.pdf` | Current-sense amplifier (шунт OCP, gain 20/50/100/200) | TI | https://www.ti.com/lit/ds/symlink/ina181.pdf |
| `LM393.pdf` / `LM393-N.pdf` | Dual comparator (пороги FAULT/PG) | TI | https://www.ti.com/lit/ds/symlink/lm393.pdf , https://www.ti.com/lit/ds/symlink/lm393-n.pdf |

Примечания:
- `BSC070N10NS3` (SR-переключатели, Infineon) не сохранён: infineon.com отдаёт HTML вместо PDF при автоматическом скачивании; исходники брать вручную с https://www.infineon.com/dgdl/Infineon-BSC070N10NS3-DS-v02_09-EN.pdf.
- L6599A — улучшенная ревизия L6599 с тем же назначением (резонансный полумост, 50% скважность), тот же вывод (SO-16); в схеме используется символ `Regulator_Controller:L6599`.
# Auditoria do runtime Windows Pure C (Qwen Turbo)

Data da inspeção: 19/11/2026. Escopo: executável experimental e DLLs instalados
somente em `%LOCALAPPDATA%\BFS\qwen3_tts\purec\bin`. Nenhum desses binários
ou modelos está no Git. Esta auditoria registra metadados dos pacotes e não é
parecer jurídico nem autorização para redistribuir.

## Runtime que o executável importa

O `ldd` do MSYS2 portátil identificou estes imports não fornecidos pelo Windows
base. `pacman -Qo` mapeou cada DLL para o pacote local; `pacman -Qi` forneceu
versão e identificadores SPDX:

| DLL instalada | Pacote/versão | Licenças declaradas pelo pacote | SHA-256 |
|---|---|---|---|
| `msys-2.0.dll` | `msys2-runtime 3.6.12-1` | GPL-3.0-or-later | `D5983ECCF5AC3340BC35774F68E576EA1735EB01E7A7578D9BFB30E8B065A5E2` |
| `msys-gcc_s-seh-1.dll` | `gcc-libs 16.2.0-1` | LGPL-2.1-or-later; GPL-3.0-or-later WITH GCC-exception-3.1; GFDL-1.3-or-later | `38118E2BB6231318025EFDFD8FC836BAA6697E0E9EC9F9AC25DEDDCDDA4BD136` |
| `libopenblas.dll` | `mingw-w64-x86_64-openblas 0.3.34-1` | BSD-3-Clause (pacote inclui avisos LAPACK) | `336E3F763E7564568F3DB155D7426E0095A6BF3E8DCE15DE81E3B3BCADE1054A` |
| `libgcc_s_seh-1.dll` | `mingw-w64-x86_64-libgcc 16.2.0-7` | GPL-3.0-or-later WITH GCC-exception-3.1; GFDL-1.3-or-later | `3776DAE2A0A196651BC9A5F3E79CFDEBCF7A63C7AC522A9B2F9B1604996E1E1B` |
| `libgfortran-5.dll` | `mingw-w64-x86_64-libgfortran 16.2.0-7` | GPL-3.0-or-later WITH GCC-exception-3.1; GFDL-1.3-or-later | `FFCC606500A98DA350E2D35EA913D1B2A86036BFFA79E56009E11E3CD01B07C3` |
| `libgomp-1.dll` | `mingw-w64-x86_64-libgomp 16.2.0-7` | GPL-3.0-or-later WITH GCC-exception-3.1; GFDL-1.3-or-later | `5618C32EBA0B9CCB7C9896435E0D51DD53C958F001887323A79D7303EF10396A` |
| `libquadmath-0.dll` | `mingw-w64-x86_64-libquadmath 16.2.0-7` | LGPL-2.1-or-later; GFDL-1.2-or-later | `F0EB395863FED82E9ED0C3C8CA2D3DFF6E683E3421FA26EAE0FEEB3F8EEE930B` |
| `libwinpthread-1.dll` | `mingw-w64-x86_64-libwinpthread 14.0.0.r598.ge3d18511f-1` | MIT; BSD-3-Clause | `98A4FEA591385952CAD1C532F4A92606358630976E9EDE5FCF115AB945305A09` |

The Pure C source is upstream commit
[`ef339be58a778b062e1c14382347964552eae007`](https://github.com/gabriele-mastrapasqua/qwen3-tts/tree/ef339be58a778b062e1c14382347964552eae007)
under MIT. The local executable contains the documented loopback-only bind
change; SHA-256:
`3A5F89D923BFDBEA29327BD4111ECD651AFA3EF448B2643B6EA8AD63DD907D13`.

Package metadata comes from the exact local MSYS2 package database. Upstream
references: [MSYS2 runtime package scripts](https://github.com/msys2/MSYS2-packages/tree/master/msys2-runtime),
[MSYS2 MinGW package scripts](https://github.com/msys2/MINGW-packages),
[OpenBLAS license information](https://www.openmathlib.org/OpenBLAS/docs/), and
[GCC Runtime Library Exception](https://www.gnu.org/licenses/gcc-exception-3.1.html).

License texts/exception notices are present in
`%LOCALAPPDATA%\BFS\qwen3_tts\purec\licenses`, including the previously
missing `gcc-libs-COPYING.LIB` and `gcc-libs-RUNTIME.LIBRARY.EXCEPTION`.

## Distribution decision

Do not package this build in a public installer or release yet. In particular,
`msys-2.0.dll` comes from a GPL-3.0-or-later runtime. The exact source archive,
notices and any applicable corresponding-source requirements have not been
assembled or reviewed for a Berofel Studio distribution. DLLs under GCC
Runtime Library Exception carry that exception only as applicable to each
file's actual notices; it must not be inferred from the package name alone.
The local licenses folder is for this experimental installation, not a
redistribution bundle.

An isolated attempt to compile with the available LLVM-MinGW 23.1.6 toolchain
avoiding MSYS imports stopped at concrete POSIX porting gaps: `posix_memalign`
is undeclared, `sys/mman.h` is absent, and `setenv` is undeclared. The server
and model loader also use `mmap`, POSIX descriptors and pthread APIs. No
replacement binary was promoted; the loopback-hardened MSYS2 build remains the
only tested executable, strictly local and experimental.

No global PATH or Windows firewall rule was changed. The editor's offline
integration tests used local model/profile paths and
`HF_HUB_OFFLINE=1`/`TRANSFORMERS_OFFLINE=1`; they did not disable all network
access at the operating-system level. A strict whole-machine network-blocked
test remains unverified.

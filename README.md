# ci

Общий выпуск репозиториев Haltia (ADR 0002 и 0004 в
[device-lenovo-b8000h](https://github.com/haltia-de/device-lenovo-b8000h)):
по тегу `vX.Y.Z` проверить, что версии в файлах совпадают с тегом, собрать и
подписать пакет Alpine 3.24 (`noarch` или одна-три из `armv7`, `aarch64`,
`x86_64` через пробел) и выложить его с `SHA256SUMS` в GitHub Release. Файлы
чужих архитектур называются `name.<arch>.apk`; armv7 и noarch — без суффикса.
Репозиторий пакетов [haltia-de/packages](https://github.com/haltia-de/packages)
собирает их в подписанный индекс.

- `.github/workflows/apk.yml` — переиспользуемый workflow (вызов — в его
  заголовке); нужен секрет организации `B8K_APK_PRIVKEY` (закрытый ключ проекта).
- `build-apk.sh` — сборка пакета в контейнере `alpine:3.24` нужной
  архитектуры (иначе ошибка); наши зависимости — из репозитория Haltia,
  остальное — из Alpine.
- `keys/` — открытый ключ, которым подписаны пакеты.

Политика версий — SemVer: X — несовместимые изменения (команды, форматы
файлов, ключи `X-Haltia-…`, API `haltia_kit`), Y — новые возможности, Z —
исправления и изменения упаковки. Тег = `pkgver` = версия в metainfo и
`pyproject.toml`; `pkgrel` всегда 0.

## Что нового: NEWS.md

Описание изменений пишется в `NEWS.md` репозитория, по-русски и
по-английски (формат — в заголовке `news.py`):

```markdown
## 2.6.0 (2026-10-20)

### Русский

- Пункт списка.

### English

- A list item.
```

`python3 news.py metainfo NEWS.md data/X.metainfo.xml` переписывает из него
раздел `<releases>` metainfo (английский — основной текст AppStream,
русский — перевод `xml:lang="ru"`); `apk.yml` проверяет, что они совпадают
(`--check`), когда `NEWS.md` есть. Первый `NEWS.md` из нынешних описаний:
`python3 news.py bootstrap data/X.metainfo.xml > NEWS.md`. Из metainfo
пакетов haltia-de/packages собирает каталог AppStream рядом с индексом apk,
и «Настройки → Обновления» показывают «Что нового» по нему, не скачивая
пакет.

Лицензия — GPL-2.0.

## deb и Flatpak

Рядом с `apk.yml` — `deb.yml` (пакеты `debian/` для Ubuntu 24.04 noble,
Ubuntu 26.04 resolute и Debian 13 trixie, lintian) и `flatpak.yml` (манифест в образе GNOME с
Flathub). Оба кладут файлы в выпуск тега со своими `SHA256SUMS.deb` и
`SHA256SUMS.flatpak` и проверяют каждый загруженный файл по sha256. В
`release.yml` репозитория:

```yaml
  deb:
    needs: apk
    uses: haltia-de/ci/.github/workflows/deb.yml@v1
  flatpak:
    needs: apk
    uses: haltia-de/ci/.github/workflows/flatpak.yml@v1
    with:
      manifest: packaging/flatpak/io.github.haltia_de.<Программа>.yml
```

`needs: apk` — чтобы выпуск создавал один job. Версия в
`debian/changelog` должна быть версией тега.

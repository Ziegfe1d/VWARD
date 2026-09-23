# Чек-лист публичного релиза

Используется на этапах RP2 и RETAIL (после RC1, RC2 и RP1). Полная последовательность и
доказательства: [`MASTER_PLAN_0.2_TO_FINAL.md`](MASTER_PLAN_0.2_TO_FINAL.md).

- [ ] нет PrivateKey/PresharedKey/API tokens;
- [ ] нет домашних IP/hostname, кроме документированных fallback-примеров;
- [ ] нет персональных DNS query logs;
- [ ] installer не трогает системный nginx;
- [ ] installer не трогает AGH;
- [ ] binding только LAN;
- [ ] backup до любых изменений;
- [ ] rollback проверен;
- [ ] uninstall проверен;
- [ ] обновление проверяет скачанный файл;
- [ ] README проверен на чистом устройстве;
- [ ] указаны поддерживаемые KeeneticOS/модели;
- [ ] LICENSE присутствует;
- [ ] screenshots не содержат личных данных;

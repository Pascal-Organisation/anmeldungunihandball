# Analyse my.sport.uni-bonn.de (Stand 14.10.2026)

Öffentliche Kursseiten `https://my.sport.uni-bonn.de/course/K00001` … `K00349`
abgerufen (277 existieren). Technik: Laravel + Livewire, Login über Filament
(`/account/login`, E-Mail + Passwort + „Angemeldet bleiben“, kein Captcha,
Login-Drosselung aktiv). Session-Cookie `mysport-session` gilt 2 h.

## Zwei Buchungsarten

| Art | Anzahl | Erkennungsmerkmal auf der Seite | Beispiele |
|---|---|---|---|
| **Einzeltermin** | 22 | „Dieser Kurs ist nur als Einzeltermin buchbar“ + Block „Termin auswählen“ (Wochenauswahl, `selectedOccurrenceId`) | **Handball** K00077, **Volleyball** K00046/49/51/58/87/89, **Basketball** K00047/48/52/54/343, **Badminton** K00020/21/27/28/298, Tanzen K00327 |
| **Ganzer Zeitraum** | 255 | Block „Belegung – Plätze frei“, keine Terminauswahl | **Fußball** K00119/125/128, **Futsal** K00130/135, Frisbee K00103/105, alle Tanz-/Fitness-/Kampfsportkurse |

Bei Einzelterminen gibt es zwei Regeln:
- „Termine buchbar bis 1 Tage im Voraus“ – offene Spielkurse (Ballsporthallen)
- „Alle zukünftigen Termine buchbar“ – Workshops/Vermietung (K00243, K00250, K00262, K00275)

Noch unklar (erst nach Login sichtbar): ob bei Einzelterminen ab dem
Verkaufsstart **alle** Wochen sofort buchbar sind oder nur ein rollierendes
Fenster. Danach richtet sich, ob der Bot zum Verkaufsstart alle Termine auf
einmal oder jede Woche einzeln bucht.

## Verkaufsstart

Gestaffelt, fast alles am **15.10.2026**: 08:00, 08:30, 09:00 (u. a. alle
Einzeltermin-Spielkurse), 09:30, 10:00, 10:30, 11:00, 11:30, 12:00. Einige
erst ab 19.10.2026, einzelne 08.02.2027 / 19.07.2027. Text auf der Seite:
„Buchbar ab TT.MM.JJJJ HH:MM“.

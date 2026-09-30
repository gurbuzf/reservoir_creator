# -*- coding: utf-8 -*-
"""Turkish interface text, keyed by the English source string.

Terms follow Turkish dam-engineering usage: *kot* is an elevation above mean
sea level (so "m a.s.l." becomes plain "m" next to "kot"), *talveg* the
riverbed, *memba* / *mansap* upstream / downstream.  Placeholders ``{...}``
must stay in the same order as in the English text (a unit test checks it).
"""

STRINGS = {
    # plugin / panel
    'Draw a line across a valley and see the reservoir behind it':
        'Vadiye bir çizgi çizin, arkasındaki rezervuarı görün',
    'Draw a line across a valley, see the reservoir': 'Vadiye çizgi çizin, rezervuarı görün',
    'Dock': 'Yerleştir',
    'Undock': 'Ayır',
    'Attach this window to the QGIS window': 'Bu pencereyi QGIS penceresine yerleştir',
    'Show this panel as a separate window': 'Bu paneli ayrı pencere olarak göster',
    'Start over: clear the line and the results': 'Baştan başla: çizgiyi ve sonuçları temizle',
    'Theme, language and help': 'Tema, dil ve yardım',
    'Theme': 'Tema',
    'Language': 'Dil',
    'Auto (follow QGIS)': "Otomatik (QGIS'e uy)",
    'Light': 'Açık',
    'Dark': 'Koyu',
    'Documentation': 'Dokümantasyon',
    'Create reservoir': 'Rezervuar oluştur',
    'Cancel': 'İptal',
    'Stop the download / calculation': 'İndirmeyi / hesabı durdur',
    'Draw a line across a valley to begin.': 'Başlamak için vadiye bir çizgi çizin.',

    # pages: references and guide
    'References': 'Kaynaklar',
    'Guide': 'Kılavuz',
    'Reservoir Creator': 'Reservoir Creator',
    'Version {} · by Faruk Gurbuz': 'Sürüm {} · Faruk Gürbüz',
    'Free and open source, GNU General Public License v3.':
        'Özgür ve açık kaynak, GNU Genel Kamu Lisansı v3.',
    'GitHub repository': 'GitHub deposu',
    'Report an issue': 'Sorun bildir',
    'Elevation data': 'Yükseklik verisi',
    'Please cite the elevation data you use in your work.':
        'Çalışmanızda kullandığınız yükseklik verisine lütfen atıf yapın.',
    'Licence': 'Lisans',
    'Built with': 'Kullanılan yazılımlar',
    'How to use': 'Nasıl kullanılır',
    'Tips': 'İpuçları',
    'Draw the dam line': 'Baraj eksenini çizin',
    'In step 1 choose "Draw on map" and click from one side of the valley to the other; '
    'right-click to finish (Backspace removes the last point, Esc cancels). Or choose "From '
    'layer" to use a line layer.':
        'Adım 1\'de "Haritada çiz"i seçin ve vadinin bir yakasından diğerine tıklayın; bitirmek '
        'için sağ tıklayın (Backspace son noktayı siler, Esc iptal eder). Ya da bir çizgi '
        'katmanı kullanmak için "Katmandan"ı seçin.',
    'Choose the elevation data': 'Yükseklik verisini seçin',
    'In step 2 pick a DEM layer from the project, or "Download": GEDTM30 (bare earth, '
    'recommended) or Copernicus GLO-30 (surface model). Only the area around the line is '
    'downloaded, and it is kept for later runs.':
        'Adım 2\'de projeden bir DEM katmanı seçin ya da "İndir"i kullanın: GEDTM30 (çıplak '
        'arazi, önerilen) veya Copernicus GLO-30 (yüzey modeli). Yalnızca çizginin çevresi '
        'indirilir ve sonraki hesaplar için saklanır.',
    'Set a limit (optional)': 'Sınır belirleyin (isteğe bağlı)',
    'Tick "Limit the water level" to use a design maximum water level (m a.s.l.) or a '
    'maximum depth above the riverbed at the line. Without a limit the water rises to the '
    'lower end of the line.':
        'Tasarım maksimum su kotu ya da çizgideki talvegden itibaren maksimum derinlik '
        'kullanmak için "Su kotunu sınırla"yı işaretleyin. Sınır yoksa su, çizginin alçak '
        'ucuna kadar yükselir.',
    'Create the reservoir': 'Rezervuarı oluşturun',
    'Press "Create reservoir". The analysis area grows by itself until the whole reservoir '
    'fits; you can cancel at any time.':
        '"Rezervuar oluştur"a basın. Analiz alanı, rezervuarın tamamı sığana kadar kendiliğinden '
        'büyür; istediğiniz zaman iptal edebilirsiniz.',
    'Read the results': 'Sonuçları okuyun',
    'Step 3 shows the stored volume, the water level, the surface area and the maximum depth, '
    'the elevation–area–volume curves, the ground profile along the line and the table. '
    'Hover over the charts for exact values.':
        'Adım 3; depolanan hacmi, su kotunu, yüzey alanını ve maksimum derinliği, kot–alan–hacim '
        'eğrilerini, çizgi boyunca zemin profilini ve tabloyu gösterir. Kesin değerler için '
        'imleci grafiklerin üzerinde gezdirin.',
    'Use the results': 'Sonuçları kullanın',
    '"Add to map" adds the outline, the line and a water-depth raster; "Export" saves a '
    'GeoPackage, a GeoTIFF, a CSV table or a chart image.':
        '"Haritaya ekle" rezervuar sınırını, çizgiyi ve su derinliği rasterını ekler; "Dışa '
        'aktar" GeoPackage, GeoTIFF, CSV tablo ya da grafik görüntüsü olarak kaydeder.',
    'If the reservoir appears on the downstream side, press the ⇄ button to compute the '
    'other side of the line.':
        'Rezervuar mansap tarafında görünürse, çizginin diğer tarafını hesaplamak için ⇄ '
        'düğmesine basın.',
    'For very large areas turn on "Fast mode" in step 2: lower resolution, faster.':
        'Çok büyük alanlar için adım 2\'de "Hızlı mod"u açın: daha düşük çözünürlük, daha hızlı.',
    'A warning about a low point in the rim means the water would escape there first; the '
    'point is marked on the map.':
        'Sırttaki bir eşikle ilgili uyarı, suyun önce oradan taşacağı anlamına gelir; nokta '
        'haritada işaretlenir.',
    '"Start over" (↻) clears the line and the results. Theme and language are in the ⚙ menu.':
        '"Baştan başla" (↻) çizgiyi ve sonuçları temizler. Tema ve dil ⚙ menüsündedir.',
    'Step timings are written to View ▸ Panels ▸ Log Messages, tab "Reservoir Creator".':
        'Adım süreleri Görünüm ▸ Paneller ▸ Günlük İletileri\'nde, "Reservoir Creator" '
        'sekmesine yazılır.',
    'Full documentation': 'Ayrıntılı dokümantasyon',

    # step 1
    'Dam line': 'Baraj ekseni',
    'The water level (above mean sea level) is the ground height at the lower end of the '
    'line, unless you set a lower limit.':
        'Su kotu (ortalama deniz seviyesine göre), daha düşük bir sınır girmediğiniz sürece '
        'çizginin alçak ucundaki zemin kotudur.',
    'Draw on map': 'Haritada çiz',
    'From layer': 'Katmandan',
    'Draw line': 'Çizgi çiz',
    'Clear': 'Temizle',
    'Click from one side of the valley to the other, right-click to finish. Backspace '
    'removes the last point, Esc cancels.':
        'Vadinin bir yakasından diğerine tıklayın, bitirmek için sağ tıklayın. Backspace son '
        'noktayı siler, Esc iptal eder.',
    'Use the selected feature': 'Seçili objeyi kullan',
    'No line yet.': 'Henüz çizgi yok.',
    '✔ Line: {:,.0f} m long': '✔ Çizgi: {:,.0f} m uzunluğunda',
    'Limit the water level': 'Su kotunu sınırla',
    'Optional. Use it when the design maximum is lower than the crest (freeboard).\n'
    'The water level is then the lower of your limit and the ground at the lower\n'
    'end of the line. A limit above that is reported and the line is used.':
        'İsteğe bağlı. Tasarım maksimumu kret kotundan düşükse (hava payı) kullanın.\n'
        'Su kotu, sınırınız ile çizginin alçak ucundaki zemin kotundan düşük olanıdır.\n'
        'Bundan yüksek bir sınır girilirse bildirilir ve çizgi kullanılır.',
    'Maximum water level': 'Maksimum su kotu',
    'Maximum depth': 'Maksimum derinlik',
    'Water level above mean sea level': 'Ortalama deniz seviyesine göre su kotu',
    'Depth above the riverbed at the line': 'Çizgideki talvegden itibaren derinlik',
    'Maximum depth above the riverbed at the line':
        'Çizgideki talvegden itibaren maksimum derinlik',
    'Maximum water level above mean sea level':
        'Ortalama deniz seviyesine göre maksimum su kotu',
    'm a.s.l.': 'm',

    # step 2
    'Elevation data (DEM)': 'Yükseklik verisi (DEM)',
    'Project layer': 'Proje katmanı',
    'Download': 'İndir',
    'Add the downloaded DEM to the project': "İndirilen DEM'i projeye ekle",
    'Fast mode (reduce the resolution for large areas)':
        'Hızlı mod (büyük alanlarda çözünürlüğü düşür)',
    'Off: the DEM is used at its own resolution.\nOn: areas above {:,.0f} million cells are '
    'coarsened for speed; the results are then less precise.':
        'Kapalı: DEM kendi çözünürlüğünde kullanılır.\nAçık: {:,.0f} milyon hücreden büyük '
        'alanlar hız için kabalaştırılır; sonuçlar daha az hassas olur.',
    '{} Only the area around the line is downloaded; you can cancel at any time.':
        '{} Yalnızca çizginin çevresi indirilir; istediğiniz zaman iptal edebilirsiniz.',
    'GEDTM30 - global bare-earth DTM, 30 m': 'GEDTM30 - küresel çıplak arazi modeli (DTM), 30 m',
    'Copernicus GLO-30 - global surface model (DSM), 30 m':
        'Copernicus GLO-30 - küresel yüzey modeli (DSM), 30 m',
    'Bare-earth terrain (vegetation and buildings removed). Recommended for reservoir '
    'studies. Heights: EGM2008.':
        'Çıplak arazi (bitki örtüsü ve yapılar çıkarılmış). Rezervuar çalışmaları için '
        'önerilir. Yükseklikler: EGM2008.',
    'Surface model: includes forest canopy and buildings, which makes valleys look '
    'shallower. Heights: EGM2008.':
        'Yüzey modeli: orman örtüsünü ve yapıları içerir, bu da vadileri daha sığ gösterir. '
        'Yükseklikler: EGM2008.',

    # step 3 - results
    'Reservoir': 'Rezervuar',
    'Stored volume': 'Depolanan hacim',
    'Water level': 'Su kotu',
    'Water level above mean sea level: the ground at the lower end of the line, or your '
    'maximum if that is lower':
        'Ortalama deniz seviyesine göre su kotu: çizginin alçak ucundaki zemin kotu ya da '
        'daha düşükse girdiğiniz maksimum',
    'Surface area': 'Yüzey alanı',
    'Area of the water surface': 'Su yüzeyinin alanı',
    'Max. depth': 'Maks. derinlik',
    'Water level − lowest point of the reservoir': 'Su kotu − rezervuarın en düşük noktası',
    'million m³ behind the line, water level {:.1f} m above mean sea level, set by {}':
        'milyon m³ depolama; su kotu {:.1f} m, belirleyen: {}',
    'Full resolution · {:.1f} m': 'Tam çözünürlük · {:.1f} m',
    'Fast mode · {:.0f} m': 'Hızlı mod · {:.0f} m',
    'a low point in the rim': 'sırttaki bir eşik',
    'low point in the rim': 'sırttaki eşik',
    'your maximum water level': 'girdiğiniz maksimum su kotu',
    'maximum level': 'maksimum kot',
    'your maximum depth': 'girdiğiniz maksimum derinlik',
    'maximum depth': 'maksimum derinlik',
    'the lower end of the line': 'çizginin alçak ucu',
    'lower end of the line': 'çizginin alçak ucu',
    'E-A-V curve': 'Kot-Alan-Hacim',
    'Profile': 'Profil',
    'Table': 'Tablo',
    'Charts': 'Grafikler',
    'Elevation - area - volume curves': 'Kot - alan - hacim eğrileri',
    'Elevation (m a.s.l.)': 'Kot (m)',
    'Area (km²)': 'Alan (km²)',
    'Volume (hm³)': 'Hacim (hm³)',
    'Install matplotlib to see the charts.': 'Grafikleri görmek için matplotlib yükleyin.',
    'Add to map': 'Haritaya ekle',
    'Add the reservoir outline, the line and the water depth as layers':
        'Rezervuar sınırını, çizgiyi ve su derinliğini katman olarak ekle',
    'Export': 'Dışa aktar',
    'GeoPackage (outline, line, table)…': 'GeoPackage (sınır, çizgi, tablo)…',
    'Water depth (GeoTIFF)…': 'Su derinliği (GeoTIFF)…',
    'Table (CSV)…': 'Tablo (CSV)…',
    'Copy table': 'Tabloyu kopyala',
    'Chart image (PNG)…': 'Grafik görüntüsü (PNG)…',
    'Upstream side guessed wrong? The plugin decides by itself which side of the line is\n'
    'upstream (where water is held back). If the blue reservoir is on the downstream side,\n'
    'click here to compute it on the other side of the line.':
        'Memba tarafı yanlış mı belirlendi? Eklenti, çizginin hangi tarafının memba\n'
        '(suyun tutulduğu taraf) olduğuna kendisi karar verir. Mavi rezervuar mansap\n'
        'tarafında görünüyorsa, hesabı çizginin diğer tarafında yapmak için tıklayın.',
    'Zoom to the reservoir': 'Rezervuara yakınlaş',
    'Export table': 'Tabloyu dışa aktar',
    'Export to GeoPackage': 'GeoPackage olarak dışa aktar',
    'Export water depth': 'Su derinliğini dışa aktar',
    'Save chart': 'Grafiği kaydet',
    'PNG image (*.png)': 'PNG görüntü (*.png)',
    'Saved {}': 'Kaydedildi: {}',
    'Reservoir added to the project.': 'Rezervuar projeye eklendi.',
    'Table copied to the clipboard.': 'Tablo panoya kopyalandı.',
    'Elevation data: {} ({}).': 'Yükseklik verisi: {} ({}).',
    '{} (download)': '{} (indirilen)',

    # status / messages
    'Click across the valley; right-click to finish.':
        'Vadi boyunca tıklayın; bitirmek için sağ tıklayın.',
    'Line ready. Press "Create reservoir" to compute.':
        'Çizgi hazır. Hesaplamak için "Rezervuar oluştur"a basın.',
    'Line ready. Now choose the elevation data (step 2).':
        'Çizgi hazır. Şimdi yükseklik verisini seçin (adım 2).',
    'Settings changed. Press "Create reservoir" to update the results.':
        'Ayarlar değişti. Sonuçları güncellemek için "Rezervuar oluştur"a basın.',
    'Still stopping the previous run - try again in a moment.':
        'Önceki hesap hâlâ durduruluyor - birazdan tekrar deneyin.',
    'Draw a line across the valley first (step 1).': 'Önce vadiye bir çizgi çizin (adım 1).',
    'Choose a DEM layer, or switch to "Download" (step 2).':
        'Bir DEM katmanı seçin ya da "İndir"e geçin (adım 2).',
    'The DEM must be a file-based raster layer.': 'DEM dosya tabanlı bir raster katman olmalı.',
    'Cancelling…': 'İptal ediliyor…',
    'Cancelled.': 'İptal edildi.',
    'Something went wrong.': 'Bir şeyler ters gitti.',
    'Reservoir at {:.1f} m a.s.l.: {} million m³, {} km².':
        'Rezervuar, kot {:.1f} m: {} milyon m³, {} km².',
    'Drawing cancelled.': 'Çizim iptal edildi.',
    'Click at least two points across the valley.': 'Vadi boyunca en az iki nokta tıklayın.',
    'Line: {:,.0f} m · {} points - right-click to finish, Backspace to undo, Esc to cancel':
        'Çizgi: {:,.0f} m · {} nokta - bitirmek için sağ tık, geri almak için Backspace, '
        'iptal için Esc',

    # charts
    'Draw a line across a valley to see this chart.':
        'Bu grafiği görmek için vadiye bir çizgi çizin.',
    'Elevation – area – volume': 'Kot – alan – hacim',
    'Volume': 'Hacim',
    'Surface area (km²)': 'Yüzey alanı (km²)',
    '{:.1f} m a.s.l. · {}': 'Kot {:.1f} m · {}',
    'Riverbed {:.1f} m a.s.l.': 'Talveg kotu {:.1f} m',
    'Elevation   {:.2f} m a.s.l.\nDepth   {:.1f} m\nVolume   {} hm³\nSurface area   {} km²':
        'Kot   {:.2f} m\nDerinlik   {:.1f} m\nHacim   {} hm³\nYüzey alanı   {} km²',
    'Ground profile along the line': 'Çizgi boyunca zemin profili',
    'Distance along the line (m)': 'Çizgi boyunca mesafe (m)',
    'End {:.1f} m': 'Uç {:.1f} m',
    'Distance   {:,.0f} m\nGround   {:.1f} m a.s.l.': 'Mesafe   {:,.0f} m\nZemin kotu   {:.1f} m',
    '\nWater depth   {:.1f} m': '\nSu derinliği   {:.1f} m',

    # layers / clipboard
    'Water depth': 'Su derinliği',
    'Elevation-area-volume': 'Kot-alan-hacim',
    'Reservoir {:.1f} m a.s.l.': 'Rezervuar (kot {:.1f} m)',
    'Water level (m a.s.l.)\tArea (km²)\tVolume (million m³)':
        'Su kotu (m)\tAlan (km²)\tHacim (milyon m³)',

    # analysis
    'Reading elevation data…': 'Yükseklik verisi okunuyor…',
    'Finding the upstream side…': 'Memba tarafı belirleniyor…',
    'Filling the reservoir…': 'Rezervuar dolduruluyor…',
    'Tracing the shoreline…': 'Kıyı çizgisi çıkarılıyor…',
    'Reservoir reaches the {} edge of the window - extending it to {:.0f} km…':
        "Rezervuar pencerenin {} kenarına ulaştı - {:.0f} km'ye genişletiliyor…",
    ' and ': ' ve ',
    'west': 'batı',
    'south': 'güney',
    'east': 'doğu',
    'north': 'kuzey',
    'The line needs at least two points.': 'Çizgi en az iki noktadan oluşmalı.',
    'An end of the line is outside the DEM (no elevation there).':
        'Çizginin bir ucu DEM dışında (orada yükseklik yok).',
    'The line does not cross a valley: no point along it is lower than its ends.':
        'Çizgi bir vadiyi kesmiyor: üzerinde uçlarından daha alçak bir nokta yok.',
    'The line is too close to the DEM edge or a no-data area.':
        'Çizgi DEM kenarına ya da veri olmayan bir alana çok yakın.',
    'No reservoir forms behind this line. Try the other side (Flip side) or check the DEM.':
        "Bu çizginin arkasında rezervuar oluşmuyor. Diğer tarafı deneyin (tarafı değiştir) ya "
        "da DEM'i kontrol edin.",
    'The maximum water level ({:.1f} m a.s.l.) is not above the riverbed at the line '
    '({:.1f} m a.s.l.): no reservoir.':
        'Maksimum su kotu ({:.1f} m), çizgideki talveg kotunun ({:.1f} m) üzerinde değil: '
        'rezervuar oluşmaz.',
    'Fast mode': 'Hızlı mod',
    'Computed at full DEM resolution ({:.1f} m cells).':
        'Tam DEM çözünürlüğünde hesaplandı ({:.1f} m hücre).',
    'Water level limited to your maximum of {:.1f} m a.s.l.; the lower end of the line is '
    '{:.1f} m higher ({:.1f} m a.s.l.).':
        'Su kotu girdiğiniz {:.1f} m maksimum ile sınırlandı; çizginin alçak ucu {:.1f} m daha '
        'yüksekte (kot {:.1f} m).',
    'Water level limited to your maximum depth of {:.1f} m above the riverbed at the line '
    '({:.1f} m a.s.l.), i.e. {:.1f} m a.s.l.; the lower end of the line is {:.1f} m higher.':
        'Su kotu, girdiğiniz {:.1f} m maksimum derinlikle sınırlandı (çizgideki talveg kotu '
        '{:.1f} m), yani kot {:.1f} m; çizginin alçak ucu {:.1f} m daha yüksekte.',
    'maximum water level ({:.1f} m a.s.l.)': 'maksimum su kotu ({:.1f} m)',
    'maximum depth ({:.1f} m, i.e. {:.1f} m a.s.l.)':
        'maksimum derinlik ({:.1f} m, yani kot {:.1f} m)',
    'Your {} is higher than the line can hold: water would flow around its lower end at '
    '{:.1f} m a.s.l., so that level is used. Draw the line further up the valley sides to '
    'allow more.':
        'Girdiğiniz {} çizginin tutabileceğinden yüksek: su, çizginin alçak ucunun etrafından '
        '{:.1f} m kotunda dolanır, bu nedenle bu kot kullanıldı. Daha yüksek kot için çizgiyi '
        'vadi yamaçlarında daha yukarıya çizin.',
    'Water escapes through a low point in the rim at {:.1f} m a.s.l., below the intended '
    'level ({:.1f} m a.s.l.). The reservoir is shown at {:.1f} m a.s.l.; the escape point is '
    'marked on the map.':
        'Su, {:.1f} m kotundaki bir sırt eşiğinden taşıyor; bu, hedeflenen kotun ({:.1f} m) '
        'altında. Rezervuar {:.1f} m kotunda gösteriliyor; taşma noktası haritada işaretli.',
    'The reservoir reaches the edge of the DEM at {:.1f} m a.s.l., so it is cut there. Use a '
    'DEM covering the whole valley.':
        "Rezervuar {:.1f} m kotunda DEM'in kenarına ulaşıyor ve orada kesiliyor. Tüm vadiyi "
        "kapsayan bir DEM kullanın.",
    'The reservoir reaches missing DEM data (no-data) at {:.1f} m a.s.l., so it is cut there.':
        'Rezervuar {:.1f} m kotunda eksik DEM verisine (no-data) ulaşıyor ve orada kesiliyor.',
    'The reservoir continues beyond the analysis area, which cannot grow further at full '
    'resolution ({:,.0f} million cells). Turn on "Fast mode" to follow it further.':
        'Rezervuar analiz alanının ötesine uzanıyor; alan tam çözünürlükte daha fazla '
        'büyütülemiyor ({:,.0f} milyon hücre). Devamını izlemek için "Hızlı mod"u açın.',

    # terrain
    'The DEM has no coordinate reference system.': "DEM'in koordinat referans sistemi yok.",
    'The DEM has no data around the line.': "DEM'de çizginin çevresinde veri yok.",
    'The DEM has no no-data value; cells equal to 0 were treated as no-data.':
        "DEM'de no-data değeri tanımlı değil; 0 değerli hücreler veri yok kabul edildi.",
    'At full resolution ({:.1f} m cells) the analysis area holds {:,.0f} million cells, more '
    'than this computer can safely process ({:,.0f} million). Turn on "Fast mode" to reduce '
    'the resolution, or use a DEM clipped to the valley.':
        'Tam çözünürlükte ({:.1f} m hücre) analiz alanı {:,.0f} milyon hücre içeriyor; bu, bu '
        'bilgisayarın güvenle işleyebileceğinden ({:,.0f} milyon) fazla. Çözünürlüğü düşürmek '
        'için "Hızlı mod"u açın ya da vadiye kırpılmış bir DEM kullanın.',
    'The line lies outside the DEM.': "Çizgi DEM'in dışında.",
    'Cannot open the DEM: {}': 'DEM açılamadı: {}',
    'Could not read/reproject the DEM: {}': 'DEM okunamadı / yeniden projekte edilemedi: {}',
    'Cannot write {}': 'Yazılamadı: {}',
    'Fast mode: DEM resampled to {:.1f} m cells.':
        'Hızlı mod: DEM {:.1f} m hücrelere yeniden örneklendi.',
    'Fast mode: DEM coarsened {}x to {:.1f} m cells.':
        'Hızlı mod: DEM {}x kabalaştırıldı ({:.1f} m hücre).',

    # downloads
    'Locating {}…': '{} aranıyor…',
    'Could not open GEDTM30 at {}. Check your internet connection / proxy.':
        'GEDTM30 açılamadı: {}. İnternet bağlantınızı / proxy ayarlarınızı kontrol edin.',
    'Could not assemble Copernicus tiles.': 'Copernicus paftaları birleştirilemedi.',
    'Zenodo could not be reached; using the known GEDTM30 location.':
        "Zenodo'ya ulaşılamadı; bilinen GEDTM30 adresi kullanılıyor.",
    'Download failed: {}\nThe {} server may be slow or unreachable right now; try again '
    'later or choose another DEM source.':
        'İndirme başarısız: {}\n{} sunucusu şu anda yavaş ya da erişilemez olabilir; daha '
        'sonra tekrar deneyin veya başka bir DEM kaynağı seçin.',
    'No Copernicus GLO-30 tiles cover this area (open sea?) or the server is unreachable.':
        'Bu alanı kapsayan Copernicus GLO-30 paftası yok (açık deniz?) ya da sunucuya '
        'ulaşılamıyor.',
    'The downloaded DEM contains no data for this area.':
        'İndirilen DEM bu alan için veri içermiyor.',
    'Downloading {} (only the area around the line)… press Cancel to stop':
        "{} indiriliyor (yalnızca çizginin çevresi)… durdurmak için İptal'e basın",
    'Downloading {}… {:.0f}% · {:.0f} s{} (press Cancel to stop)':
        '{} indiriliyor… {:.0f}% · {:.0f} sn{} (durdurmak için İptal)',
    'Downloading {}: tile {} of {} · {:.0f} s{} (press Cancel to stop)':
        '{} indiriliyor: pafta {} / {} · {:.0f} sn{} (durdurmak için İptal)',
    ', retry {}': ', deneme {}',
    'Could not assemble the DEM tiles: {}': 'DEM paftaları birleştirilemedi: {}',
}

* orders.csv 
    name,    type,   logic_type,  value,   key_role,   admissibility_of_the_pass,   exemple,   discovered_problems
 - order_id, str, str, унікальний id ключ замовлення, Primary Key, Ні, S06-O0005997, рядок 6000 має однаковий id з 3597
 - customer_id, str, str, id ключ клієнта який оформив замовлення, Foreign Key, Ні, S06-C000211, Замовлення № S06-O0003981 має невідомий id ключ клієнта
 - merchant_id, str, str, id ключ надавача послуг, Foreign Key, Ні, S06-M00036, Замовлення № S06-O0001794 має невідомий id ключ надавача послуг
 - created_at, str, datetime, час в якому було створено замовлення, сортувальну, Ні, 2025-12-07T12:52:20Z, має некоректні значення у замовлені № S06-O0001102 та № S06-O0001818
 - order_status, str, str, Статус замовлення, сортувальну, Ні, delivered, Немає
 - currency, str, str, валюта в якій було оформлено транзакцію, сортувальну, Ні, UAH, в замовлені № S06-O0000964 замість UAH написано UA H
 - subtotal_amount, float64, float64, проміжна ціна, Ні, Ні, 941.4, немає
 - delivery_fee, float64, float64, ціна за доставку, Ні, так, 99.31, немає
 - discount_amount1, float64, float64, сума знижки, Ні, так, 188.28, немає
 - total_amount, float64, float64, загальна сума замовлення, ні, ні, 259.80, немає

* customers.csv
    name,    type,   logic_type,  value,   key_role,   admissibility_of_the_pass,   exemple,   discovered_problems 
 - customer_id, str, str, унікальний id ключ клієнта, Primary Key, Ні, S06-C000001, рядок 359 та 800 має один id ключ клієнта
 - full_name, str, str, повне ім'я клієнта, немає, Ні, Roman Moroz, немає
 - email, str, str, електронна пошта клієнта, немає, Ні, s06.customer000001@example.test, клієнти S06-C000270, S06-C000703, S06-C000360 та клієнт за рядком 800 мають однакову пошту
 - phone, float64, int, контактний номер телефону клієнта, немає, так, 3.809689e+11, у п'ятьох клієнтів, а саме S06-C000242, S06-C000267, S06-C000360, S06-C000550, S06-C000742 не вказаний номер телефону.
 - city, str, str, місто проживання клієнта, немає, Ні, Kyiv, запис клієнта S06-C000028 має зайвий пробіл на початку назви міста " Kyiv"
 - service_zone_id, str, str, id ключ зони обслуговування, немає, Ні, KYI-Z04, немає
 - registered_at, str, datetime, час та дата реєстрації клієнта, сортувальну, Ні, 2024-11-26T16:13:18.859859510Z, немає
 - customer_status, str, categorical, поточний статус акаунту клієнта, сортувальну, Ні, active, немає
 
* merchants.csv
    name,    type,   logic_type,  value,   key_role,   admissibility_of_the_pass,   exemple,   discovered_problems
 - merchant_id, str, str, унікальний id ключ надавача послуг, Primary Key, Ні, рядки 24 та 42 повністю дублюються, відповідно і merchant_id у них дублюються
 - merchant_name, str, str, назва закладу, немає, Ні, Family Point 01, немає
 - merchant_type, str, categorical, категорія закладу, немає, Ні, restaurant, у надавача № S06-M00019 категорія записана у верхньому регістрі "RESTAURANT"
 - city, str, categorical, місто розташування закладу, немає, Ні, Odesa, немає
 - service_zone_id, str, str, id ключ зони обслуговування, немає, Ні, ODE-Z02, немає
 - opened_at, str, datetime, дата та час реєстрації/відкриття закладу, сортувальну, Ні, 2024-05-17T10:01:55.569007497Z, немає
 - merchant_status, str, categorical, статус активності закладу, сортувальну, Ні, active, немає
 
* products.csv
    name,    type,   logic_type,  value,   key_role,   admissibility_of_the_pass,   exemple,   discovered_problems
 - product_id, str, str, унікальний id ключ товару, Primary Key, Ні, S06-P000001, товар S06-P000315 задубльований (повна копія у рядках 314 та 503)
 - merchant_id, str, str, id ключ надавача послуг якому належить товар, Foreign Key, Ні, S06-M00001, товар S06-P000365 посилається на невідомий заклад S06-M99999
 - product_name, str, str, назва товару, немає, Ні, Tiramisu, немає
 - category, str, categorical, категорія товару, немає, Ні, desserts, запис S06-P000246 має зайвий пробіл в назві категорії " Bakery"
 - unit_price_uah, float64, decimal, ціна одиниці товару в гривнях, немає, Ні, 118.25, товар S06-P000324 має нульовою ціною
 - is_active, bool, boolean, статус доступності товару до замовлення, немає, Ні, True, немає
 - updated_at, str, datetime, дата та час останнього оновлення запису про товар, сортувальну, Ні, 2026-06-22T16:36:35.287736380Z, немає

-- Week 8 Version 3
USE magazine;
-- Q1 -- Magazine name with 37% off the price, rounded to 2 decimal places
SELECT magazineName
,      ROUND(magazinePrice * .63, 2) AS '37% off'
FROM   magazine;

-- Q2 -- show how long in years (Rounded to the nearest year) 
--       has it been since subscription has started (use 2021-04-23 as 'todays' date)
SELECT subscriberKey
,      ROUND(DATEDIFF('2021-04-23',subscriptionStartDate)/365) AS 'Years since subscription'
FROM   subscription;

-- Q3 -- Show subscriptionStartDate and subscriptionLength
--       Add them together to find how long their subscription will go.
--       Format all dates to be like: 09 01, 23
SELECT DATE_FORMAT(subscriptionStartDate, '%m %d, %y') AS subscriptionStartDate
,      subscriptionLength
,      DATE_FORMAT(DATE_ADD(subscriptionStartDate, INTERVAL subscriptionLength MONTH), '%m %d, %y') AS 'Subscription End'
FROM   subscription;

USE bike;
-- Q4 -- list of product names without the product name. Sort by product_id. Grab the first 14.
SELECT RIGHT(product_name, LENGTH(product_name) - LOCATE('- ', product_name) +1) AS 'Product Name w/o product'
FROM   product
ORDER BY product_id
LIMIT 14; 
-- SELECT RIGHT(SUBSTRING_INDEX(product_name, ' -',1)) AS 'Product Name w/o Product' ??

-- Q5 -- List 2019 model bikes, their price, amount needed for 20% down payment
--       divide remaining balance into 7 equal payments.
--       Display all monetary values with a $, a comma at the thousands place and 2 decimals.
SELECT product_name
,     CONCAT('$',list_price) AS Price
,     CONCAT('$',FORMAT(list_price * .2,2)) AS '20% down'
,     CONCAT('$',FORMAT((list_price * .8)/7,2)) AS 'Seven Equal Payments'
FROM   product
WHERE  model_year = 2019;
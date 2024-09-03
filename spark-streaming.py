## spark streaming scrit to process the retail data from kafka topic into the JSON files stored on hdfs.
# created by: Prerna Gupta
# Importing libraries and functions
from pyspark.sql import SparkSession
from pyspark.sql.functions import *
from pyspark.sql.types import *
from pyspark.sql.window import Window

#creating SparkSession
spark = SparkSession  \
    .builder  \
    .appName("RetailDataKPI")  \
    .getOrCreate()
spark.sparkContext.setLogLevel('ERROR')

# Creating UDFs
#Checking for a new order
def is_order(type):
   if type=="ORDER":
       return 1
   else:
       return 0

#Checking for return of an order
def is_return(type):
   if type=="RETURN":
       return 1
   else:
       return 0

# Calculating the total number of items
def total_items(items):
    if items is not None:
        item_count =0
        for item in items:
            item_count = item_count + item['quantity']
        return item_count

# Calculating the total cost of the order
def total_cost(items,type):
    if items is not None:
        total_cost =0
        item_price =0
    for item in items:
        item_price = (item['quantity']*item['unit_price'])
        total_cost = total_cost+ item_price
        item_price=0
    if type  == 'RETURN':
        return total_cost *(-1)
    else:
        return total_cost

# Register UDFs
is_order = udf(is_order, IntegerType())
is_return = udf(is_return, IntegerType())
add_total_items = udf(total_items, IntegerType())
add_total_cost = udf(total_cost, FloatType())



# Reading input data from Kafka topic
raw_data_stream = spark \
    .readStream \
    .format("kafka") \
    .option("kafka.bootstrap.servers","18.211.252.152:9092") \
    .option("subscribe","real-time-project") \
    .option("startingOffsets", "latest")  \
    .load()

# Defininig json Schema
json_Schema = StructType() \
    .add("invoice_no", LongType()) \
    .add("country",StringType()) \
    .add("timestamp", TimestampType()) \
    .add("type", StringType()) \
    .add("items", ArrayType(StructType([
        StructField("SKU", StringType()),
        StructField("title", StringType()),
        StructField("unit_price", FloatType()),
        StructField("quantity", IntegerType())
        ])))

orders_stream_data = raw_data_stream.select(from_json(col("value").cast("string"), json_Schema).alias("data")).select("data.*")


# Calculating additional columns from the stream
orders_stream_output = orders_stream_data \
   .withColumn("total_cost", add_total_cost(orders_stream_data.items,orders_stream_data.type)) \
   .withColumn("total_items", add_total_items(orders_stream_data.items)) \
   .withColumn("is_order", is_order(orders_stream_data.type)) \
   .withColumn("is_return", is_return(orders_stream_data.type))


# Writing the summarised input table to the console
orders_batch = orders_stream_output \
   .select("invoice_no", "country", "timestamp","total_cost","total_items","is_order","is_return") \
   .writeStream \
   .outputMode("append") \
   .format("console") \
   .option("truncate", "false") \
   .option("path", "/Console_output") \
   .option("checkpointLocation", "/Console_output_checkpoints") \
   .trigger(processingTime="1 minute") \
   .start()

# Calculating Time based KPIs
agg_on_time = orders_stream_output \
    .withWatermark("timestamp","1 minutes") \
    .groupby(window("timestamp", "1 minute")) \
    .agg(sum("total_cost").alias("total_volume_of_sales"),
        avg("total_cost").alias("average_transaction_size"),
        count("invoice_no").alias("OPM"),
        avg("is_return").alias("rate_of_return")) \
    .select("window.start","window.end","OPM","total_volume_of_sales","average_transaction_size","rate_of_return")

# Calculating Time and country based KPIs
agg_on_time_country = orders_stream_output \
    .withWatermark("timestamp", "1 minutes") \
    .groupBy(window("timestamp", "1 minutes"), "country") \
    .agg(sum("total_cost").alias("total_volume_of_sales"),
        count("invoice_no").alias("OPM"),
        avg("is_return").alias("rate_of_return")) \
    .select("window.start","window.end","country", "OPM","total_volume_of_sales","rate_of_return")

# Writing to the json files in hdfs : Time based KPI values
ByTime = agg_on_time.writeStream \
    .format("json") \
    .outputMode("append") \
    .option("truncate", "false") \
    .option("path", "timeKPIvalue") \
    .option("checkpointLocation", "timeKPIvalue_cp") \
    .trigger(processingTime="1 minutes") \
    .start()

# Writing to the hdfs : Time and country based KPI values
ByTime_country = agg_on_time_country.writeStream \
    .format("json") \
    .outputMode("append") \
    .option("truncate", "false") \
    .option("path", "time_countryKPIvalue") \
    .option("checkpointLocation", "time_countryKPIvalue_cp") \
    .trigger(processingTime="1 minutes") \
    .start()

orders_batch.awaitTermination()
ByTime.awaitTermination()
ByTime_country.awaitTermination()

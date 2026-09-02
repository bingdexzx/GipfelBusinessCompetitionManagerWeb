from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("companies", "0002_initial"),
    ]

    operations = [
        # 移除 company_field_values.version 单列索引：
        # 该索引仅用于乐观锁 UPDATE ... WHERE pk AND version=期望，无单列 version 查询，
        # 属于冗余索引，增写开销且无收益（# P2 设计项）。
        migrations.RemoveIndex(
            model_name="companyfieldvalue",
            name="company_fie_version_4db5e3_idx",
        ),
    ]

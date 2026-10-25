# Demo页面版导航

PPT：`D:/GIT/RehabAffectPerception/output/presentations/Demo2_实习项目三天学习_20260912_Demo页面版_定稿.pptx`

本版在原36页中新增6页，调整4页原有截图，共42页。以下10页包含Demo实际界面。原讲解版保留。

| 页码 | 页面与操作 | 对应源码（src/rehab_affect/） |
|---|---|---|
| 5 | 提交课堂视频：课程批次、名额、选择视频 | demo2_portal.py:312；student_record_store.py:1543 |
| 6 | 本课程任务：排队、处理中、证据就绪 | demo2_portal.py:559；demo2_media_worker.py:107 |
| 7 | 人物确认：重新检测、手动画框、选择姓名 | demo2_identity.py:245；scenario_lab_server.py:1637 |
| 21 | 漏检后手动画框与当前帧确认 | demo2_identity.py:245；demo2_identity_store.py:536 |
| 22 | 已确认记录与“查看后续5秒”入口 | scenario_lab_server.py:1654；demo2_identity_store.py:645 |
| 33 | IEP资料版本1与版本2 | demo2_dossier_store.py:476 |
| 34 | 选择学生与资料版本，保存课堂引用 | demo2_dossier_store.py:657 |
| 35 | 登记资料授权与期限 | demo2_dossier_store.py:438 |
| 36 | 公司后台的数量和运行状态 | demo2_dossier_store.py:698 |
| 38 | 撤回和删除后的资料访问状态 | demo2_dossier_store.py:461；demo2_dossier_store.py:381 |

当前待答问题仍是：“点击自动定位后，模型完成了什么，接下来还需要教师做什么？”可对照第7页。模型卡和推理代码从原第5、7页顺延为第8、10页。

第5、6页直接使用现有render_demo2_upload_html生成页面，由浏览器路由提供虚构课程和任务；全部请求本地拦截，没有访问真实服务、数据库或提交视频。处理45%为教学数据，不是本轮媒体实测。第7、21、22页来自此前合成图像隔离测试，自动检测被显式设为不可用；第22页只展示跟随入口，不证明跟随结果。第33—36、38页来自既有虚构档案测试。第33页左右为同一页面两个版本记录的局部放大。第38页是先删除版本2、再撤回授权后的状态。

截图仅用于讲解页面和代码关系，不充当真实课堂模型精度或教学效果证据。每次仍按学习者本人回答评估，不因更新课件标记掌握。

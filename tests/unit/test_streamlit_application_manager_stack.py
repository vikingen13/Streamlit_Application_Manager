import aws_cdk as core
import aws_cdk.assertions as assertions

from streamlit_application_manager.streamlit_application_manager_stack import StreamlitApplicationManagerStack

# example tests. To run these tests, uncomment this file along with the example
# resource in streamlit_application_manager/streamlit_application_manager_stack.py
def test_sqs_queue_created():
    app = core.App()
    stack = StreamlitApplicationManagerStack(app, "streamlit-application-manager")
    template = assertions.Template.from_stack(stack)

#     template.has_resource_properties("AWS::SQS::Queue", {
#         "VisibilityTimeout": 300
#     })

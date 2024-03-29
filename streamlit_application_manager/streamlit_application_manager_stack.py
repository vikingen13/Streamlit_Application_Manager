from aws_cdk import (
    Duration,
    Stack,
    NestedStack,
    aws_codecommit as codecommit,
    aws_codepipeline as codepipeline,
    aws_codepipeline_actions as codepipeline_actions,
    aws_codebuild as codebuild,
    aws_cognito as cognito,
    aws_secretsmanager as secretsmanager,
    aws_ecs as ecs,
    aws_ecr as ecr,
    aws_elasticloadbalancingv2 as elbv2,
    aws_ec2 as ec2,
    aws_s3 as s3,
    RemovalPolicy,
    aws_iam as iam,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    SecretValue,
    CfnOutput

    # aws_sqs as sqs,
)
import os
from constructs import Construct

from config_file import Config
from utils.helpers import helpers

CUSTOM_HEADER_NAME = "X-Custom-Header"
CUSTOM_HEADER_VALUE = "sdmlkfsdmlkf"

class StreamlitApplicationManagerStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)


        # Create Cognito user pool
        user_pool = cognito.UserPool(self, "StreamlitApplicationsUserPool")

        # Create Cognito client
        user_pool_client = cognito.UserPoolClient(self, f"StreamlitApplicationsUserPoolClient",
                                                  user_pool=user_pool,
                                                  generate_secret=True
                                                  )
        

        # Store Cognito parameters in a Secrets Manager secret
        secret = secretsmanager.Secret(self, "StreamlitApplicationsParamCognitoSecret",
                                       secret_object_value={
                                           "pool_id": SecretValue.unsafe_plain_text(user_pool.user_pool_id),
                                           "app_client_id": SecretValue.unsafe_plain_text(user_pool_client.user_pool_client_id),
                                           "app_client_secret": user_pool_client.user_pool_client_secret
                                       },
                                       # This secret name should be identical
                                       # to the one defined in the Streamlit
                                       # container
                                       secret_name="StreamlitApplicationsParamCognitoSecret"
                                       )




        # Deploy an ECS Cluster named "StreamLit Cluster in a new VPC on 2 AZ
        cluster = ecs.Cluster(self, "StreamlitApplicationsCluster",
                              vpc=ec2.Vpc(self, "StreamlitApplicationsVPC", max_azs=2),
                              cluster_name="StreamlitApplicationsCluster")


        #create an ALB that will connect to the cluster services and will be accessed through a cloudfront distribution
        alb = elbv2.ApplicationLoadBalancer(self, "StreamlitApplicationsALB",
                                      vpc=cluster.vpc,
                                      internet_facing=True,
                                      load_balancer_name="StreamlitApplications-alb")
        

        # Add ALB as CloudFront Origin
        origin = origins.LoadBalancerV2Origin(
            alb,
            custom_headers={CUSTOM_HEADER_NAME: CUSTOM_HEADER_VALUE},
            origin_shield_enabled=False,
            protocol_policy=cloudfront.OriginProtocolPolicy.HTTP_ONLY,
        )

        cloudfront_distribution = cloudfront.Distribution(
                    self,
                    f"StreamlitApplicationsCfDist",
                    default_behavior=cloudfront.BehaviorOptions(
                        origin=origin,
                        viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                        allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
                        cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                        origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER,
                    ),
                )


        #create a listener on the ALB that will forward traffic to the cluster services
        listener = alb.add_listener("StreamlitApplicationsListener",
                                    port=80,
                                    open=True)
        #create a default action for the listener that return 404 error
        listener.add_action("DefaultAction",
                            action=elbv2.ListenerAction.fixed_response(status_code=404))

        #create a S3 bucket for applications content
        application_content_bucket = s3.Bucket(self, "StreamlitApplicationsBucket",
                            removal_policy=RemovalPolicy.DESTROY,
                            auto_delete_objects=True)

        
        # Grant access to Bedrock
        bedrock_policy = iam.Policy(self, "StreamlitApplicationsBedrockPolicy",
                                    statements=[
                                        iam.PolicyStatement(
                                            actions=["bedrock:InvokeModel"],
                                            resources=["*"]
                                        )
                                    ]
                                    )
        
        #grant access to transcribe
        transcribe_policy = iam.Policy(self, "StreamlitApplicationsTranscribePolicy",
                                        statements=[
                                            iam.PolicyStatement(
                                                actions=["transcribe:StartTranscriptionJob",    
                                                         "transcribe:UntagResource",
                                                        "transcribe:GetTranscriptionJob",
                                                        "transcribe:TagResource",
                                                        "transcribe:StartTranscriptionJob",
                                                        "transcribe:ListTranscriptionJobs",
                                                        "transcribe:ListTagsForResource"],
                                                resources=["*"]
                                            )
                                        ]
                                        )
        
        myNestedStacks = []

        #for each application in the config file, we create an app and add a trarget rule
        for i,app_name in enumerate(Config.APPLICATION_LIST):
            #create a stack with the streamlit application
            myNestedStack = StreamlitApplicationStack(self, f"{app_name}Stack",
                                    app_name=app_name,
                                    StreamlitCluster=cluster
                                    )
            
            #create a path based routing rule on the listener that will forward traffic to the service
            listener.add_targets(app_name,
                                target_group_name=app_name,
                                port=8501,
                                priority=helpers.get_hash(app_name),
                                health_check=elbv2.HealthCheck(path=f'/{app_name}/'),
                                conditions=[
                                    elbv2.ListenerCondition.http_header(CUSTOM_HEADER_NAME,[CUSTOM_HEADER_VALUE]),
                                    elbv2.ListenerCondition.path_patterns([f"/{app_name}/*"])
                                    ],
                                    protocol=elbv2.ApplicationProtocol.HTTP,
                                    targets=[myNestedStack.service]
                                
            )

            myNestedStack.service.task_definition.task_role.attach_inline_policy(bedrock_policy)
            myNestedStack.service.task_definition.task_role.attach_inline_policy(transcribe_policy)

            # Grant access to read the secret in Secrets Manager
            secret.grant_read(myNestedStack.service.task_definition.task_role)
            
            # Grant access to write to the bucket
            application_content_bucket.grant_read_write(myNestedStack.service.task_definition.task_role, f"{app_name}/*")
            
            myNestedStacks.append(myNestedStack)

        for stack in myNestedStacks:
            CfnOutput(
                self, f"{stack.app_name}_url",
                value=f"{cloudfront_distribution.domain_name}/{stack.app_name}/",
                description="url of the application",
            )

            CfnOutput(
                self, f"{stack.app_name}_repository",
                value=f"git clone {stack.codecommitrepo.repository_clone_url_grc}",
                description="to clone the application",
            )

            CfnOutput(
                self, f"{stack.app_name}_bucket",
                value=f"{application_content_bucket.bucket_name}/{stack.app_name}/",
                description="Bucket and prefix for the app"
            )

        CfnOutput(
            self, f"userPoolId",
            value=f"aws cognito-idp admin-create-user --user-pool-id {user_pool.user_pool_id} --username admin --temporary-password admin12345",
            description="to create a first user",
        )
        



class StreamlitApplicationStack(NestedStack):

    #in this stack, we create a fargate service with the same name than the stack
    #the service is on the ECS cluster of the main stack
    #the service is initialized with an ECR image created from the source code in the base_app folder
    #the ECR repository is created in the main stack
    #the service is configured to run on port 8501
    #the service is accessible from the ALB of the main stack using a path equal to the service name
    #the stack also create a code commit repository with the base_app source code that will deploy in the service
    #the service shall not have a public IP address
    def __init__(self, scope: Construct, construct_id: str, app_name: str, StreamlitCluster: ecs.Cluster, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        fargate_task_definition = ecs.FargateTaskDefinition(
            self,
            f"{app_name}TaskDefinition",
            memory_limit_mib=512,
            cpu=256,
        )

        # Build Dockerfile from local folder 
        image = ecs.ContainerImage.from_asset(directory='base_app',asset_name=app_name)

        fargate_task_definition.add_container(
            f"{app_name}-Container",            
            image=image,
            environment={
                "STREAMLIT_SERVER_BASE_URL_PATH":f"/{app_name}"
            },
            port_mappings=[
                ecs.PortMapping(
                    container_port=8501,
                    protocol=ecs.Protocol.TCP)],
            logging=ecs.LogDrivers.aws_logs(stream_prefix=f"{app_name}_ContainerLogs"),
        )


        #create an ECS service from the repository
        service = ecs.FargateService(self, f"{app_name}Service",
                                     cluster=StreamlitCluster,
                                     task_definition=fargate_task_definition,
                                     assign_public_ip=False,
                                     service_name=app_name,
                                     desired_count=1,                                     
                                     )
        
        #create an ECR repository for the app
        imagerepository = ecr.Repository(self, f"{app_name}Repository",
                                  repository_name=f"{app_name}-imagerepo",
                                  removal_policy=RemovalPolicy.DESTROY,
                                  auto_delete_images=True
                                 )
        
        #create a code commit repository from the base_app source code
        repository = codecommit.Repository(self, f"{app_name}",
                                           repository_name=f"{app_name}",
                                           code=codecommit.Code.from_directory("base_app/")
                                            )
        #create a pipeline to deploy the code commit repository in the service
        pipeline = codepipeline.Pipeline(self, f"{app_name}Pipeline",
                                            pipeline_name=f"{app_name}Pipeline"
                                        )
        source_output = codepipeline.Artifact()
        source_action = codepipeline_actions.CodeCommitSourceAction(
            action_name="CodeCommit",
            repository=repository,
            output=source_output
        )
        pipeline.add_stage(
            stage_name="Source",
            actions=[source_action]
        )

        build_output = codepipeline.Artifact()
        #create a codebuild project to build the docker images from the source code in the code commit repository
        docker_build_project = codebuild.PipelineProject(
            self, "DockerBuild",
            project_name=f"{app_name}-Docker-Build",
            build_spec=codebuild.BuildSpec.from_source_filename(
                filename='docker_build_buildspec.yml'),
            environment=codebuild.BuildEnvironment(
                privileged=True,
                build_image=codebuild.LinuxBuildImage.STANDARD_5_0
            ),
            # pass the ecr repo uri into the codebuild project so codebuild knows where to push
            environment_variables={
                'ecr': codebuild.BuildEnvironmentVariable(
                    value=imagerepository.repository_name),
                'tag': codebuild.BuildEnvironmentVariable(
                    value='cdk'),
                'container': codebuild.BuildEnvironmentVariable(
                    value=f"{app_name}-Container"),
            },
            description='Pipeline for CodeBuild',
            timeout=Duration.minutes(60),
        )

        
        docker_build= codepipeline_actions.CodeBuildAction(
                            action_name='DockerBuildImages',
                            input=source_output,
                            outputs=[build_output],
                            project=docker_build_project,
                            run_order=1,
                        )

         

        # codebuild permissions to interact with ecr
        imagerepository.grant_pull_push(docker_build_project)
        imagerepository.grant_pull_push(service.task_definition.execution_role)

        pipeline.add_stage(
            stage_name="DockerBuild",
            actions=[docker_build]
        )

        deploy_action = codepipeline_actions.EcsDeployAction(
            action_name="ECS_Deploy",
            service=service,
            input=build_output,
        )

        pipeline.add_stage(
            stage_name="Deploy",
            actions=[deploy_action]
        )

        self.service = service
        self.app_name = app_name
        self.codecommitrepo = repository
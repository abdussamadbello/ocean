from typing import Any, Dict, List, AsyncGenerator, Optional

from loguru import logger

from .auth import AuthenticationError
from .base_client import SpaceliftBaseClient


class SpaceliftDataClients(SpaceliftBaseClient):
    """Data client methods for fetching different types of Spacelift resources."""

    async def get_spaces(self) -> AsyncGenerator[List[Dict[str, Any]], None]:
        """Get all spaces with pagination."""
        logger.info("Fetching Spacelift spaces")

        query = """
        query GetSpaces {
            spaces {
                id
                name
                description
                parentSpace
                labels
            }
        }
        """

        try:
            data = await self.make_graphql_request(query)
            spaces = data["data"]["spaces"] or []

            if spaces:
                yield spaces
                logger.info(f"Fetched {len(spaces)} spaces")
            else:
                yield []
                logger.info("No spaces found")

        except AuthenticationError as e:
            logger.warning(
                "Authorization failed for spaces query. This may indicate insufficient permissions."
            )
            logger.warning(f"Full error: {e}")
            logger.info("Trying simplified spaces query...")

            simple_query = """
            query GetBasicSpaces {
                spaces {
                    id
                    name
                }
            }
            """

            try:
                data = await self.make_graphql_request(simple_query)
                spaces = data["data"]["spaces"] or []

                for space in spaces:
                    space.setdefault("description", "")
                    space.setdefault("parentSpace", None)
                    space.setdefault("labels", [])

                if spaces:
                    yield spaces
                    logger.info(f"Fetched {len(spaces)} spaces using simplified query")
                else:
                    yield []
                    logger.info("No spaces found using simplified query")

            except Exception as simple_e:
                logger.error("Both full and simplified spaces queries failed.")
                logger.error(
                    "This usually indicates the API key lacks 'read' access to spaces."
                )
                logger.error("Please check your Spacelift API key permissions.")
                logger.error(f"Error details: {simple_e}")
                yield []

        except Exception as e:
            logger.warning(f"Could not fetch spaces: {e}")
            yield []

    async def get_stacks(self) -> AsyncGenerator[List[Dict[str, Any]], None]:
        """Get all stacks with pagination."""
        logger.info("Fetching Spacelift stacks")

        query = """
        query GetStacks {
            stacks {
                id
                name
                description
                repository
                branch
                state
                administrative
                space
                labels
                provider
                terraformVersion
                projectRoot
            }
        }
        """

        try:
            data = await self.make_graphql_request(query)
            stacks = data["data"]["stacks"] or []

            if stacks:
                yield stacks
                logger.info(f"Fetched {len(stacks)} stacks")
            else:
                yield []
                logger.info("No stacks found")

        except AuthenticationError as e:
            logger.warning(
                "Authorization failed for stacks query. This may indicate insufficient permissions."
            )
            logger.warning(f"Full error: {e}")
            logger.info("Trying simplified stacks query...")

            simple_query = """
            query GetBasicStacks {
                stacks {
                    id
                    name
                    description
                    repository
                    branch
                    state
                    administrative
                    space
                }
            }
            """

            try:
                data = await self.make_graphql_request(simple_query)
                stacks = data["data"]["stacks"] or []  

                for stack in stacks:
                    stack.setdefault("labels", [])
                    stack.setdefault("provider", "")
                    stack.setdefault("terraformVersion", "")
                    stack.setdefault("projectRoot", "")

                if stacks:
                    yield stacks
                    logger.info(f"Fetched {len(stacks)} stacks using simplified query")
                else:
                    yield []
                    logger.info("No stacks found using simplified query")

            except Exception as simple_e:
                logger.error("Both full and simplified stacks queries failed.")
                logger.error(
                    "This usually indicates the API key lacks 'read' access to stacks."
                )
                logger.error("Please check your Spacelift API key permissions.")
                logger.error(f"Error details: {simple_e}")
                yield []

        except Exception as e:
            logger.warning(f"Could not fetch stacks: {e}")
            yield []

    async def get_deployments(self) -> AsyncGenerator[List[Dict[str, Any]], None]:
        """Get all deployments (tracked runs) with pagination."""
        logger.info("Fetching Spacelift deployments")

        stack_ids = []
        async for stacks_batch in self.get_stacks():
            for stack in stacks_batch:
                stack_ids.append(stack["id"])

        if not stack_ids:
            logger.info("No stacks found, yielding empty deployments list")
            yield []
            return

        for stack_id in stack_ids:
            logger.debug(f"Fetching deployments for stack: {stack_id}")
            async for deployments_batch in self._get_stack_runs(
                stack_id, run_type="TRACKED"
            ):
                yield deployments_batch

    async def _get_stack_runs(
        self, stack_id: str, run_type: Optional[str] = None
    ) -> AsyncGenerator[List[Dict[str, Any]], None]:
        """Get runs for a specific stack."""
        query = """
        query GetStackRuns($stackId: ID!) {
            stack(id: $stackId) {
                id
                name
                runs {
                    id
                    type
                    state
                    branch
                    createdAt
                    updatedAt
                    triggeredBy
                    commit {
                        hash
                        message
                        authorName
                    }
                    driftDetection
                }
            }
        }
        """

        variables = {"stackId": stack_id}

        try:
            data = await self.make_graphql_request(query, variables)

            stack_data = data.get("data", {}).get("stack") if data else None
            if not stack_data:
                yield []
                return

            runs = stack_data.get("runs", []) or []
            filtered_runs = []

            for run in runs:
                if run_type and run.get("type") != run_type:
                    continue

                run["url"] = None
                run["delta"] = {"added": 0, "changed": 0, "deleted": 0}

                run["stack_id"] = stack_id
                run["stack"] = {
                    "id": stack_data.get("id", stack_id),
                    "name": stack_data.get("name", "Unknown"),
                }
                filtered_runs.append(run)

            yield filtered_runs

        except Exception as e:
            logger.warning(f"Could not fetch runs for stack {stack_id}: {e}")

            try:
                logger.info(f"Attempting fallback query for stack {stack_id}")
                simple_query = """
                query GetBasicStackRuns($stackId: ID!) {
                    stack(id: $stackId) {
                        id
                        name
                        runs {
                            id
                            type
                            state
                            createdAt
                        }
                    }
                }
                """

                data = await self.make_graphql_request(simple_query, variables)
                stack_data = data.get("data", {}).get("stack") if data else None

                if stack_data:
                    runs = stack_data.get("runs", []) or []
                    filtered_runs = []

                    for run in runs:
                        if run_type and run.get("type") != run_type:
                            continue

                        run.update(
                            {
                                "branch": None,
                                "updatedAt": None,
                                "triggeredBy": None,
                                "commit": {
                                    "hash": None,
                                    "message": None,
                                    "authorName": None,
                                },
                                "driftDetection": False,
                                "url": None,
                                "delta": {"added": 0, "changed": 0, "deleted": 0},
                                "stack_id": stack_id,
                                "stack": {
                                    "id": stack_data.get("id", stack_id),
                                    "name": stack_data.get("name", "Unknown"),
                                },
                            }
                        )
                        filtered_runs.append(run)

                    yield filtered_runs
                else:
                    yield []

            except Exception as fallback_e:
                logger.warning(
                    f"Fallback query also failed for stack {stack_id}: {fallback_e}"
                )
                yield []

    async def get_policies(self) -> AsyncGenerator[List[Dict[str, Any]], None]:
        """Get all policies."""
        logger.info("Fetching Spacelift policies")

        query = """
        query GetPolicies {
            policies {
                id
                name
                type
                body
                space
                labels
            }
        }
        """

        try:
            data = await self.make_graphql_request(query)
            policies = data["data"]["policies"] or []
            if policies:
                yield policies
                logger.info(f"Fetched {len(policies)} policies")
            else:
                yield []
                logger.info("No policies found")

        except Exception as e:
            logger.warning(
                f"Could not fetch policies - may require admin permissions: {e}"
            )
            yield []

    async def get_users(self) -> AsyncGenerator[List[Dict[str, Any]], None]:
        """Get all users."""
        logger.info("Fetching Spacelift users")

        query = """
        query GetBasicManagedUsers {
            managedUsers {
                id
                username
                invitationEmail
                status
                role
                lastLoginTime
            }
        }
        """

        try:
            data = await self.make_graphql_request(query)
            managed_users = data["data"]["managedUsers"] or []

            users = []
            for user in managed_users:
                user_data = {
                    "id": user.get("id"),
                    "name": user.get("username", ""),
                    "username": user.get("username"),
                    "email": user.get("invitationEmail"),
                    "status": user.get("status"),
                    "role": user.get("role"),
                    "lastLoginTime": user.get("lastLoginTime"),
                }
                users.append(user_data)

            if users:
                yield users
                logger.info(f"Fetched {len(users)} managed users")
            else:
                yield []
                logger.info("No managed users found")

        except Exception as e:
            logger.warning(
                f"Could not fetch managed users - may require admin permissions: {e}"
            )
            yield []
